"""The Atlas ontology as Cognify sees it: which types exist and how to map a proposal."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_PROMPT_ENTITY_TYPES = 200
MAX_PROMPT_RELATIONSHIP_TYPES = 300
MAX_ONTOLOGY_ROWS = 2000


def type_key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").casefold())


@dataclass
class BoundOntology:
    entity_types: list[dict[str, Any]] = field(default_factory=list)
    relationship_types: list[dict[str, Any]] = field(default_factory=list)
    graph_id: str = ""
    version: int = 0
    source: str = "project"
    strict: bool = True

    def __post_init__(self) -> None:
        self._entities = {
            type_key(_name(t)): t for t in self.entity_types if type_key(_name(t))
        }
        self._relationships: dict[str, list[dict[str, Any]]] = {}
        for t in self.relationship_types:
            key = type_key(_name(t))
            if key:
                self._relationships.setdefault(key, []).append(_as_dict(t))

    def prompt_view(self) -> dict[str, Any]:
        return {
            "entity_types": self.entity_types[:MAX_PROMPT_ENTITY_TYPES],
            "relationship_types": self.relationship_types[
                :MAX_PROMPT_RELATIONSHIP_TYPES
            ],
        }

    def map_entity(self, proposed: str) -> tuple[str, str | None] | None:
        """(type name, Atlas concept id), or None when the ontology has no such type."""
        if not self._entities:
            return proposed, None
        hit = self._entities.get(type_key(proposed))
        if hit is None:
            return None if self.strict else (proposed, None)
        d = _as_dict(hit)
        return d.get("name") or proposed, d.get("concept_id")

    def map_relationship(
        self, proposed: str, source_type: str = "", target_type: str = ""
    ) -> tuple[str, str | None] | None:
        """(type name, Atlas edge id). A declared domain and range must also fit."""
        if not self._relationships:
            return proposed, None
        rows = self._relationships.get(type_key(proposed))
        if not rows:
            return None if self.strict else (proposed, None)
        for row in rows:
            frm, to = type_key(row.get("from")), type_key(row.get("to"))
            if (not frm or frm == type_key(source_type)) and (
                not to or to == type_key(target_type)
            ):
                name = (row.get("name") or proposed).upper().replace(" ", "_")
                return name, row.get("edge_id")
        return None if self.strict else (proposed, None)


def _name(t: Any) -> str:
    return (t.get("name") or "") if isinstance(t, dict) else str(t)


def _as_dict(t: Any) -> dict[str, Any]:
    return t if isinstance(t, dict) else {"name": str(t)}


def as_bound(ontology: BoundOntology | dict | None) -> BoundOntology | None:
    if ontology is None or isinstance(ontology, BoundOntology):
        return ontology
    et, rt = (
        ontology.get("entity_types") or [],
        ontology.get("relationship_types") or [],
    )
    if not et and not rt:
        return None
    return BoundOntology(entity_types=list(et), relationship_types=list(rt))


def apply_ontology(result: Any, ontology: BoundOntology | None) -> int:
    """Retype one chunk's proposals in place and drop what does not fit. Returns the drop count."""
    if ontology is None:
        return 0
    dropped = 0
    kept_entities = []
    types: dict[str, str] = {}
    for e in result.entities:
        mapped = ontology.map_entity(e.entity_type)
        if mapped is None:
            dropped += 1
            continue
        e.entity_type, e.atlas_concept_id = mapped[0], mapped[1]
        types[e.name] = e.entity_type
        kept_entities.append(e)
    kept_rels = []
    for r in result.relationships:
        if r.source not in types or r.target not in types:
            dropped += 1
            continue
        mapped = ontology.map_relationship(
            r.relationship_type, types[r.source], types[r.target]
        )
        if mapped is None:
            dropped += 1
            continue
        r.relationship_type, r.atlas_edge_id = mapped[0], mapped[1]
        kept_rels.append(r)
    result.entities, result.relationships = kept_entities, kept_rels
    return dropped
