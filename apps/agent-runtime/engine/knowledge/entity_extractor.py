"""Entity & relationship extraction from text chunks using LLMs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field

from engine.knowledge.ontology import BoundOntology
from engine.knowledge.prompts import (
    ENTITY_EXTRACTION_SYSTEM,
    ENTITY_EXTRACTION_USER,
)
from engine.knowledge.rate_limit import CallLimiter, with_backoff

logger = logging.getLogger(__name__)

EXTRACTION_MAX_TOKENS = 8192
MAX_SPLIT_DEPTH = 2
MIN_SPLIT_CHARS = 200

DEFAULT_COGNIFY_MODEL = os.environ.get(
    "COGNIFY_DEFAULT_MODEL", "claude-haiku-4-5-20251001"
)
MAX_CHUNK_CHARS = 4000
EXPECTED_OUTPUT_TOKENS = 400
PROMPT_OVERHEAD_TOKENS = 450


def estimate_chunk_tokens(chunk_text: str) -> int:
    return (
        min(len(chunk_text), MAX_CHUNK_CHARS) // 4
        + PROMPT_OVERHEAD_TOKENS
        + EXPECTED_OUTPUT_TOKENS
    )


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    description: str
    source_chunk_index: int = 0
    source_doc_id: str = ""
    confidence: float = 1.0
    atlas_concept_id: str | None = None


@dataclass
class ExtractedRelationship:
    source: str
    target: str
    relationship_type: str
    description: str
    source_chunk_index: int = 0
    source_doc_id: str = ""
    confidence: float = 1.0
    atlas_edge_id: str | None = None


@dataclass
class ChunkExtractionResult:
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    chunk_index: int
    doc_id: str
    tokens_used: int = 0
    cost: float = 0.0
    error: str | None = None


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
    chunks_failed: int = 0


def _confidence(raw: object) -> float:
    """The model's 0-1 confidence; a missing or garbled value counts as certain."""
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    if v > 1.0 and v <= 100.0:
        v /= 100.0
    return max(0.0, min(1.0, v))


def _ontology_typing_prior(ontology: dict | BoundOntology | None) -> str:
    """Format an ontology schema as a typing prior for the LLM."""
    if not ontology:
        return ""
    if isinstance(ontology, BoundOntology):
        ontology = ontology.prompt_view()
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
            ends = ""
            if isinstance(t, dict) and t.get("from") and t.get("to"):
                ends = f" (from {t['from']} to {t['to']})"
            lines.append(f"  - {name}{ends}: {desc}")
    lines.append(
        "If text contains entities or relationships that don't fit the ontology, "
        "skip them rather than inventing a new type."
    )
    return "\n".join(lines)


def _complete_items(text: str, key: str) -> list[dict]:
    """Whole objects from a JSON array that may have been cut off."""
    at = text.find(f'"{key}"')
    at = text.find("[", at) if at >= 0 else -1
    if at < 0:
        return []
    decoder = json.JSONDecoder()
    items: list[dict] = []
    i = at + 1
    while True:
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] != "{":
            return items
        try:
            item, i = decoder.raw_decode(text, i)
        except ValueError:
            return items
        items.append(item)


def parse_extraction(text: str) -> tuple[dict, bool]:
    """The parsed reply, and whether the model ran out of room before finishing it."""
    start = text.index("{")
    try:
        return json.loads(text[start : text.rindex("}") + 1]), False
    except ValueError:
        return {
            "entities": _complete_items(text, "entities"),
            "relationships": _complete_items(text, "relationships"),
        }, True


async def extract_from_chunk(
    chunk_text: str,
    chunk_index: int,
    doc_id: str,
    existing_entities: list[str] | None = None,
    model: str = DEFAULT_COGNIFY_MODEL,
    ontology: dict | BoundOntology | None = None,
    limiter: CallLimiter | None = None,
    retries: int = 5,
    split_depth: int = 0,
) -> ChunkExtractionResult:
    """Extract entities and relationships from a single text chunk.

    A failed call comes back with error set and no cost lost, so the caller
    does not mistake it for a chunk that had nothing in it."""
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
        chunk_text=chunk_text[:MAX_CHUNK_CHARS],
    )

    # Append ontology typing prior to the system prompt when one is
    # active for the project (phase 3). Append rather than replace so
    # the rules in ENTITY_EXTRACTION_SYSTEM (JSON shape, naming
    # consistency) still apply.
    system_prompt = ENTITY_EXTRACTION_SYSTEM + _ontology_typing_prior(ontology)

    async def _call():
        if limiter is not None:
            await limiter.acquire(estimate_chunk_tokens(chunk_text))
        return await llm.complete(
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            model=model,
            temperature=0.1,  # Low temperature for consistent extraction
            max_tokens=EXTRACTION_MAX_TOKENS,
        )

    response = None
    try:
        response = await with_backoff(_call, retries=retries)

        text = response.content.strip()
        # Extract JSON from response
        if "{" not in text:
            logger.warning(
                "Entity extraction returned no JSON for chunk %d of doc %s",
                chunk_index,
                doc_id,
            )
            return ChunkExtractionResult(
                entities=[],
                relationships=[],
                chunk_index=chunk_index,
                doc_id=doc_id,
                tokens_used=response.input_tokens + response.output_tokens,
                cost=response.cost,
                error="the model returned no JSON",
            )
        data, cut_off = parse_extraction(text)

        entities = []
        for e in data.get("entities", []):
            if not e.get("name"):
                continue
            entities.append(
                ExtractedEntity(
                    name=e["name"].strip(),
                    entity_type=e.get("type", "concept").lower(),
                    description=e.get("description", ""),
                    source_chunk_index=chunk_index,
                    source_doc_id=doc_id,
                    confidence=_confidence(e.get("confidence")),
                )
            )

        relationships = []
        entity_names = {e.name for e in entities}
        for r in data.get("relationships", []):
            src = r.get("source", "").strip()
            tgt = r.get("target", "").strip()
            if not src or not tgt:
                continue
            # Only keep relationships where both entities exist
            if src in entity_names and tgt in entity_names:
                relationships.append(
                    ExtractedRelationship(
                        source=src,
                        target=tgt,
                        relationship_type=r.get("type", "RELATED_TO")
                        .upper()
                        .replace(" ", "_"),
                        description=r.get("description", ""),
                        source_chunk_index=chunk_index,
                        source_doc_id=doc_id,
                        confidence=_confidence(r.get("confidence")),
                    )
                )

        result = ChunkExtractionResult(
            entities=entities,
            relationships=relationships,
            chunk_index=chunk_index,
            doc_id=doc_id,
            tokens_used=response.input_tokens + response.output_tokens,
            cost=response.cost,
        )
        if (
            cut_off
            and split_depth < MAX_SPLIT_DEPTH
            and len(chunk_text) >= MIN_SPLIT_CHARS
        ):
            middle = len(chunk_text) // 2
            parts = await asyncio.gather(
                *(
                    extract_from_chunk(
                        part,
                        chunk_index,
                        doc_id,
                        existing_entities,
                        model,
                        ontology,
                        limiter,
                        retries,
                        split_depth + 1,
                    )
                    for part in (chunk_text[:middle], chunk_text[middle:])
                )
            )
            for part in parts:
                result.entities.extend(part.entities)
                result.relationships.extend(part.relationships)
                result.tokens_used += part.tokens_used
                result.cost += part.cost
            result.error = next((p.error for p in parts if p.error), None)
        elif cut_off:
            logger.warning(
                "Kept what fit from a cut off reply for chunk %d of doc %s",
                chunk_index,
                doc_id,
            )
        return result

    except Exception as e:
        logger.error(
            "Entity extraction failed for chunk %d of doc %s: %s",
            chunk_index,
            doc_id,
            e,
        )
        return ChunkExtractionResult(
            entities=[],
            relationships=[],
            chunk_index=chunk_index,
            doc_id=doc_id,
            tokens_used=(
                response.input_tokens + response.output_tokens if response else 0
            ),
            cost=response.cost if response else 0.0,
            error=str(e)[:500] or type(e).__name__,
        )


async def extract_chunks(
    items: list[tuple[int, str]],
    doc_id: str,
    known_entities: list[str] | None = None,
    model: str = DEFAULT_COGNIFY_MODEL,
    ontology: dict | BoundOntology | None = None,
    limiter: CallLimiter | None = None,
    max_parallel: int = 4,
) -> list[ChunkExtractionResult]:
    """A batch of (index, text) at bounded concurrency, sharing what earlier batches found."""
    gate = asyncio.Semaphore(max(1, max_parallel))

    async def one(index: int, text: str) -> ChunkExtractionResult:
        async with gate:
            return await extract_from_chunk(
                chunk_text=text,
                chunk_index=index,
                doc_id=doc_id,
                existing_entities=known_entities or None,
                model=model,
                ontology=ontology,
                limiter=limiter,
            )

    return list(await asyncio.gather(*(one(i, t) for i, t in items)))


async def extract_from_document(
    chunks: list[str],
    doc_id: str,
    filename: str,
    model: str = DEFAULT_COGNIFY_MODEL,
    ontology: dict | BoundOntology | None = None,
    limiter: CallLimiter | None = None,
    max_parallel: int = 4,
) -> DocumentExtractionResult:
    """Extract entities and relationships from all chunks of a document."""
    result = DocumentExtractionResult(doc_id=doc_id, filename=filename)
    known_entities: list[str] = []
    items = [(i, c) for i, c in enumerate(chunks) if c.strip()]
    step = max(1, max_parallel)

    for start in range(0, len(items), step):
        for chunk_result in await extract_chunks(
            items[start : start + step],
            doc_id,
            known_entities=known_entities,
            model=model,
            ontology=ontology,
            limiter=limiter,
            max_parallel=max_parallel,
        ):
            result.entities.extend(chunk_result.entities)
            result.relationships.extend(chunk_result.relationships)
            result.total_tokens += chunk_result.tokens_used
            result.total_cost += chunk_result.cost
            result.chunks_processed += 1
            result.chunks_failed += 1 if chunk_result.error else 0

            # Accumulate entity names for context in later chunks
            for e in chunk_result.entities:
                if e.name not in known_entities:
                    known_entities.append(e.name)

    logger.info(
        "Document %s (%s): extracted %d entities, %d relationships from %d chunks",
        doc_id,
        filename,
        len(result.entities),
        len(result.relationships),
        result.chunks_processed,
    )
    return result
