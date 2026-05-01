"""Entity resolution — deduplicate and merge entities across documents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from engine.knowledge.entity_extractor import ExtractedEntity, ExtractedRelationship
from engine.knowledge.prompts import ENTITY_RESOLUTION_SYSTEM, ENTITY_RESOLUTION_USER

logger = logging.getLogger(__name__)


@dataclass
class ResolvedEntity:
    """An entity after deduplication — has a canonical name and all aliases."""

    canonical_name: str
    entity_type: str
    description: str
    aliases: list[str] = field(default_factory=list)
    source_doc_ids: list[str] = field(default_factory=list)
    mention_count: int = 1
    confidence: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedRelationship:
    """A relationship with resolved entity names."""

    source: str  # Canonical name
    target: str  # Canonical name
    relationship_type: str
    description: str
    source_doc_ids: list[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass
class ResolutionResult:
    entities: list[ResolvedEntity]
    relationships: list[ResolvedRelationship]
    merges_performed: int = 0
    total_raw_entities: int = 0
    tokens_used: int = 0
    cost: float = 0.0


async def resolve_entities(
    raw_entities: list[ExtractedEntity],
    raw_relationships: list[ExtractedRelationship],
    existing_entities: list[dict[str, Any]] | None = None,
    model: str = "claude-sonnet-4-5-20250929",
) -> ResolutionResult:
    """Resolve (deduplicate) extracted entities and remap relationships."""
    total_raw = len(raw_entities)

    name_groups: dict[str, list[ExtractedEntity]] = {}
    for e in raw_entities:
        key = e.name.strip().lower()
        if key not in name_groups:
            name_groups[key] = []
        name_groups[key].append(e)

    # Also check against existing KB entities
    existing_map: dict[str, dict[str, Any]] = {}
    if existing_entities:
        for ex in existing_entities:
            existing_map[ex["canonical_name"].lower()] = ex
            for alias in ex.get("aliases") or []:
                existing_map[alias.lower()] = ex

    # Group entities whose names are very similar (within edit distance)
    # For now, use exact-match groups + existing KB matching
    merged: dict[str, ResolvedEntity] = {}
    name_to_canonical: dict[str, str] = {}
    merges = 0

    for key, group in name_groups.items():
        # Check if this entity exists in the KB already
        if key in existing_map:
            ex = existing_map[key]
            canonical = ex["canonical_name"]
        else:
            # Use the most descriptive name variant as canonical
            canonical = max(
                (e.name for e in group),
                key=lambda n: len(n),
            )

        # Determine entity type (majority vote)
        type_counts: dict[str, int] = {}
        for e in group:
            type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1
        entity_type = max(type_counts, key=type_counts.get)  # type: ignore

        # Best description (longest)
        description = max(
            (e.description for e in group if e.description),
            key=len,
            default="",
        )

        # Collect source docs
        doc_ids = list({e.source_doc_id for e in group if e.source_doc_id})

        # Collect aliases (all name variants except canonical)
        aliases = list({e.name for e in group if e.name != canonical})

        if canonical in merged:
            # Merge into existing resolved entity
            existing = merged[canonical]
            existing.mention_count += len(group)
            existing.source_doc_ids = list(set(existing.source_doc_ids + doc_ids))
            existing.aliases = list(set(existing.aliases + aliases))
            if len(description) > len(existing.description):
                existing.description = description
            merges += len(group) - 1
        else:
            merged[canonical] = ResolvedEntity(
                canonical_name=canonical,
                entity_type=entity_type,
                description=description,
                aliases=aliases,
                source_doc_ids=doc_ids,
                mention_count=len(group),
            )
            if len(group) > 1:
                merges += len(group) - 1

        # Track name → canonical mapping for relationship resolution
        for e in group:
            name_to_canonical[e.name] = canonical

    # If we have many similar-named entities, ask LLM to decide
    tokens_used = 0
    cost = 0.0

    # Only do LLM resolution if there are enough entities to warrant it
    if len(merged) > 10:
        try:
            ambiguous = _find_ambiguous_groups(list(merged.values()))
            if ambiguous:
                llm_result = await _llm_resolve(ambiguous, model)
                tokens_used = llm_result.get("tokens", 0)
                cost = llm_result.get("cost", 0.0)

                for cluster in llm_result.get("clusters", []):
                    canonical = cluster["canonical"]
                    for alias in cluster.get("aliases", []):
                        if alias in merged and alias != canonical:
                            # Merge alias entity into canonical
                            if canonical in merged:
                                merged[canonical].aliases.append(alias)
                                merged[canonical].mention_count += merged[
                                    alias
                                ].mention_count
                                merged[canonical].source_doc_ids = list(
                                    set(
                                        merged[canonical].source_doc_ids
                                        + merged[alias].source_doc_ids
                                    )
                                )
                            name_to_canonical[alias] = canonical
                            del merged[alias]
                            merges += 1
        except Exception as e:
            logger.warning("LLM entity resolution failed: %s", e)

    rel_key_map: dict[str, ResolvedRelationship] = {}
    for r in raw_relationships:
        src_canonical = name_to_canonical.get(r.source, r.source)
        tgt_canonical = name_to_canonical.get(r.target, r.target)

        # Skip relationships where entities were dropped
        if src_canonical not in merged or tgt_canonical not in merged:
            continue

        key = f"{src_canonical}|{r.relationship_type}|{tgt_canonical}"
        if key in rel_key_map:
            rel_key_map[key].weight += 0.5  # Strengthen repeated relationships
            rel_key_map[key].source_doc_ids = list(
                set(rel_key_map[key].source_doc_ids + [r.source_doc_id])
            )
        else:
            rel_key_map[key] = ResolvedRelationship(
                source=src_canonical,
                target=tgt_canonical,
                relationship_type=r.relationship_type,
                description=r.description,
                source_doc_ids=[r.source_doc_id] if r.source_doc_id else [],
            )

    logger.info(
        "Entity resolution: %d raw → %d resolved (%d merges), %d relationships",
        total_raw,
        len(merged),
        merges,
        len(rel_key_map),
    )

    return ResolutionResult(
        entities=list(merged.values()),
        relationships=list(rel_key_map.values()),
        merges_performed=merges,
        total_raw_entities=total_raw,
        tokens_used=tokens_used,
        cost=cost,
    )


def _find_ambiguous_groups(
    entities: list[ResolvedEntity],
) -> list[list[ResolvedEntity]]:
    """Find groups of entities that might be duplicates based on name similarity."""
    from difflib import SequenceMatcher

    groups: list[list[ResolvedEntity]] = []
    used = set()

    sorted_entities = sorted(entities, key=lambda e: e.canonical_name.lower())
    for i, e1 in enumerate(sorted_entities):
        if e1.canonical_name in used:
            continue
        group = [e1]
        for j in range(i + 1, len(sorted_entities)):
            e2 = sorted_entities[j]
            if e2.canonical_name in used:
                continue
            ratio = SequenceMatcher(
                None, e1.canonical_name.lower(), e2.canonical_name.lower()
            ).ratio()
            if ratio > 0.7 and e1.entity_type == e2.entity_type:
                group.append(e2)
                used.add(e2.canonical_name)
        if len(group) > 1:
            groups.append(group)
            used.add(e1.canonical_name)

    return groups


async def _llm_resolve(
    ambiguous_groups: list[list[ResolvedEntity]],
    model: str,
) -> dict[str, Any]:
    """Use LLM to resolve ambiguous entity groups."""
    from engine.llm_router import LLMRouter

    llm = LLMRouter()

    entity_list = []
    descriptions = []
    for group in ambiguous_groups:
        for e in group:
            entity_list.append(f"- {e.canonical_name} ({e.entity_type})")
            if e.description:
                descriptions.append(f"  {e.canonical_name}: {e.description}")

    user_prompt = ENTITY_RESOLUTION_USER.format(
        entity_list="\n".join(entity_list),
        entity_descriptions="\n".join(descriptions) or "(no descriptions available)",
    )

    try:
        response = await llm.complete(
            messages=[{"role": "user", "content": user_prompt}],
            system=ENTITY_RESOLUTION_SYSTEM,
            model=model,
            temperature=0.1,
        )
        text = response.content.strip()
        if "{" in text:
            result = json.loads(text[text.index("{") : text.rindex("}") + 1])
            result["tokens"] = response.input_tokens + response.output_tokens
            result["cost"] = response.cost
            return result
    except Exception as e:
        logger.warning("LLM entity resolution parsing failed: %s", e)

    return {"clusters": [], "standalone": [], "tokens": 0, "cost": 0.0}
