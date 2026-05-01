"""Entity & relationship extraction from text chunks using LLMs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from engine.knowledge.prompts import (
    ENTITY_EXTRACTION_SYSTEM,
    ENTITY_EXTRACTION_USER,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    description: str
    source_chunk_index: int = 0
    source_doc_id: str = ""
    confidence: float = 1.0


@dataclass
class ExtractedRelationship:
    source: str
    target: str
    relationship_type: str
    description: str
    source_chunk_index: int = 0
    source_doc_id: str = ""
    confidence: float = 1.0


@dataclass
class ChunkExtractionResult:
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    chunk_index: int
    doc_id: str
    tokens_used: int = 0
    cost: float = 0.0


@dataclass
class DocumentExtractionResult:
    """Aggregated extraction results for an entire document."""
    doc_id: str
    filename: str
    chunks_processed: int = 0
    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0


def _ontology_typing_prior(ontology: dict | None) -> str:
    """Format an ontology schema as a typing prior for the LLM."""
    if not ontology:
        return ""
    et = ontology.get("entity_types") or []
    rt = ontology.get("relationship_types") or []
    if not et and not rt:
        return ""
    lines = ["", "Domain ontology to follow STRICTLY:"]
    if et:
        lines.append("Entity types (pick one per entity):")
        for t in et:
            name = t.get("name") if isinstance(t, dict) else str(t)
            desc = t.get("description") if isinstance(t, dict) else ""
            lines.append(f"  - {name}: {desc}")
    if rt:
        lines.append("Relationship types (pick one per relationship):")
        for t in rt:
            name = t.get("name") if isinstance(t, dict) else str(t)
            desc = t.get("description") if isinstance(t, dict) else ""
            lines.append(f"  - {name}: {desc}")
    lines.append(
        "If text contains entities or relationships that don't fit the ontology, "
        "skip them rather than inventing a new type."
    )
    return "\n".join(lines)


async def extract_from_chunk(
    chunk_text: str,
    chunk_index: int,
    doc_id: str,
    existing_entities: list[str] | None = None,
    model: str = "claude-sonnet-4-5-20250929",
    ontology: dict | None = None,
) -> ChunkExtractionResult:
    """Extract entities and relationships from a single text chunk."""
    from engine.llm_router import LLMRouter
    llm = LLMRouter()

    # Build context about existing entities
    existing_context = ""
    if existing_entities:
        existing_context = (
            f"Previously extracted entities (use these names if referencing the same entity):\n"
            f"{', '.join(existing_entities[:50])}\n"
        )

    user_prompt = ENTITY_EXTRACTION_USER.format(
        existing_context=existing_context,
        chunk_text=chunk_text[:4000],  # Limit chunk size for LLM context
    )

    # Append ontology typing prior to the system prompt when one is
    # active for the project (phase 3). Append rather than replace so
    # the rules in ENTITY_EXTRACTION_SYSTEM (JSON shape, naming
    # consistency) still apply.
    system_prompt = ENTITY_EXTRACTION_SYSTEM + _ontology_typing_prior(ontology)

    try:
        response = await llm.complete(
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            model=model,
            temperature=0.1,  # Low temperature for consistent extraction
        )

        text = response.content.strip()
        # Extract JSON from response
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(json_str)
        else:
            logger.warning("Entity extraction returned no JSON for chunk %d of doc %s", chunk_index, doc_id)
            return ChunkExtractionResult(
                entities=[], relationships=[], chunk_index=chunk_index, doc_id=doc_id,
                tokens_used=response.input_tokens + response.output_tokens, cost=response.cost,
            )

        entities = []
        for e in data.get("entities", []):
            if not e.get("name"):
                continue
            entities.append(ExtractedEntity(
                name=e["name"].strip(),
                entity_type=e.get("type", "concept").lower(),
                description=e.get("description", ""),
                source_chunk_index=chunk_index,
                source_doc_id=doc_id,
            ))

        relationships = []
        entity_names = {e.name for e in entities}
        for r in data.get("relationships", []):
            src = r.get("source", "").strip()
            tgt = r.get("target", "").strip()
            if not src or not tgt:
                continue
            # Only keep relationships where both entities exist
            if src in entity_names and tgt in entity_names:
                relationships.append(ExtractedRelationship(
                    source=src,
                    target=tgt,
                    relationship_type=r.get("type", "RELATED_TO").upper().replace(" ", "_"),
                    description=r.get("description", ""),
                    source_chunk_index=chunk_index,
                    source_doc_id=doc_id,
                ))

        return ChunkExtractionResult(
            entities=entities,
            relationships=relationships,
            chunk_index=chunk_index,
            doc_id=doc_id,
            tokens_used=response.input_tokens + response.output_tokens,
            cost=response.cost,
        )

    except Exception as e:
        logger.error("Entity extraction failed for chunk %d of doc %s: %s", chunk_index, doc_id, e)
        return ChunkExtractionResult(
            entities=[], relationships=[], chunk_index=chunk_index, doc_id=doc_id,
        )


async def extract_from_document(
    chunks: list[str],
    doc_id: str,
    filename: str,
    model: str = "claude-sonnet-4-5-20250929",
    ontology: dict | None = None,
) -> DocumentExtractionResult:
    """Extract entities and relationships from all chunks of a document."""
    result = DocumentExtractionResult(doc_id=doc_id, filename=filename)
    known_entities: list[str] = []

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue

        chunk_result = await extract_from_chunk(
            chunk_text=chunk,
            chunk_index=i,
            doc_id=doc_id,
            existing_entities=known_entities if known_entities else None,
            model=model,
            ontology=ontology,
        )

        result.entities.extend(chunk_result.entities)
        result.relationships.extend(chunk_result.relationships)
        result.total_tokens += chunk_result.tokens_used
        result.total_cost += chunk_result.cost
        result.chunks_processed += 1

        # Accumulate entity names for context in later chunks
        for e in chunk_result.entities:
            if e.name not in known_entities:
                known_entities.append(e.name)

    logger.info(
        "Document %s (%s): extracted %d entities, %d relationships from %d chunks",
        doc_id, filename, len(result.entities), len(result.relationships), result.chunks_processed,
    )
    return result
