"""Graph Explorer Tool — direct Neo4j knowledge graph traversal."""

from __future__ import annotations

import json
import logging
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class GraphExplorerTool(BaseTool):
    name = "graph_explorer"
    description = (
        "Explore a knowledge graph (Neo4j) to find entities and relationships "
        "extracted from your documents via Cognify. Domain-agnostic. "
        "Use 'find_entity' to search for any entity by name. "
        "Use 'entity_relationships' to see how an entity connects to others. "
        "Use 'entity_path' to find the shortest connection between two entities. "
        "Use 'entities_by_type' to list all entities of a type (ORGANIZATION, LOCATION, etc.). "
        "Use 'related_documents' to find which source documents reference a given entity. "
        "Use 'graph_stats' to see how many entities and relationships exist."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "find_entity", "entity_relationships",
                    "entity_path", "entities_by_type",
                    "related_documents", "graph_stats",
                ],
                "description": "Which graph operation to perform",
            },
            "entity_name": {
                "type": "string",
                "description": "Entity name to search for (fuzzy matching supported)",
            },
            "entity_type": {
                "type": "string",
                "description": "Entity type filter (e.g. ORGANIZATION, PERSON, LOCATION, CONTRACT_TERM, ASSET, REGULATION)",
            },
            "target_entity": {
                "type": "string",
                "description": "Target entity for entity_path operation",
            },
            "max_hops": {
                "type": "integer",
                "description": "Maximum relationship hops for traversal (default 2)",
                "default": 2,
            },
        },
        "required": ["operation"],
    }

    def __init__(self, kb_id: str) -> None:
        self.kb_id = kb_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "")
        if not op:
            return ToolResult(content="Error: operation is required", is_error=True)

        try:
            from engine.knowledge.neo4j_client import is_neo4j_available, get_neo4j_session
        except ImportError:
            return ToolResult(content="Knowledge graph module not available.", is_error=True)

        if not await is_neo4j_available():
            return ToolResult(
                content="Knowledge graph (Neo4j) is not available.",
                metadata={"available": False},
            )

        try:
            if op == "graph_stats":
                return await self._graph_stats()
            elif op == "find_entity":
                return await self._find_entity(arguments)
            elif op == "entity_relationships":
                return await self._entity_relationships(arguments)
            elif op == "entity_path":
                return await self._entity_path(arguments)
            elif op == "entities_by_type":
                return await self._entities_by_type(arguments)
            elif op == "related_documents":
                return await self._related_documents(arguments)
            else:
                return ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except Exception as e:
            logger.warning("Graph explorer error: %s", e)
            return ToolResult(content=f"Graph query error: {e}", is_error=True)

    async def _graph_stats(self) -> ToolResult:
        from engine.knowledge.neo4j_client import get_neo4j_session

        async with get_neo4j_session() as session:
            entity_count = await session.run(
                "MATCH (e:Entity {kb_id: $kb_id}) RETURN count(e) as cnt",
                kb_id=self.kb_id,
            )
            e_rec = await entity_count.single()
            entities = e_rec["cnt"] if e_rec else 0

            rel_count = await session.run(
                "MATCH (a:Entity {kb_id: $kb_id})-[r]->(b:Entity {kb_id: $kb_id}) RETURN count(r) as cnt",
                kb_id=self.kb_id,
            )
            r_rec = await rel_count.single()
            rels = r_rec["cnt"] if r_rec else 0

            # Entity types
            types_result = await session.run(
                "MATCH (e:Entity {kb_id: $kb_id}) RETURN e.entity_type as type, count(e) as cnt ORDER BY cnt DESC",
                kb_id=self.kb_id,
            )
            type_counts = {r["type"]: r["cnt"] async for r in types_result}

        if entities == 0:
            return ToolResult(
                content="Knowledge graph is empty. Documents need to be processed through Cognify first to extract entities and relationships.",
                metadata={"entities": 0, "relationships": 0},
            )

        lines = [
            f"Knowledge Graph Statistics:\n",
            f"- Entities: {entities}",
            f"- Relationships: {rels}",
            f"- Entity types: {json.dumps(type_counts, indent=2)}",
        ]
        return ToolResult(
            content="\n".join(lines),
            metadata={"entities": entities, "relationships": rels, "types": type_counts},
        )

    async def _find_entity(self, args: dict) -> ToolResult:
        name = args.get("entity_name", "")
        if not name:
            return ToolResult(content="Error: entity_name is required", is_error=True)

        from engine.knowledge.neo4j_client import get_neo4j_session

        pattern = f"(?i).*{name}.*"
        async with get_neo4j_session() as session:
            result = await session.run("""
                MATCH (e:Entity {kb_id: $kb_id})
                WHERE e.canonical_name =~ $pattern
                   OR any(a IN e.aliases WHERE a =~ $pattern)
                RETURN e.canonical_name as name, e.entity_type as type,
                       e.description as desc, e.mention_count as mentions,
                       e.aliases as aliases, e.source_doc_ids as docs
                ORDER BY e.mention_count DESC
                LIMIT 10
            """, kb_id=self.kb_id, pattern=pattern)

            entities = [r async for r in result]

        if not entities:
            return ToolResult(content=f"No entities matching '{name}' found in the knowledge graph.")

        lines = [f"Found {len(entities)} entities matching '{name}':\n"]
        for e in entities:
            aliases = ", ".join(e["aliases"][:3]) if e["aliases"] else ""
            lines.append(f"- **{e['name']}** ({e['type']}) — {e['desc'][:150]}")
            if aliases:
                lines.append(f"  Aliases: {aliases}")
            lines.append(f"  Mentioned {e['mentions']} times across {len(e['docs'] or [])} documents")
        return ToolResult(content="\n".join(lines), metadata={"count": len(entities)})

    async def _entity_relationships(self, args: dict) -> ToolResult:
        name = args.get("entity_name", "")
        if not name:
            return ToolResult(content="Error: entity_name is required", is_error=True)

        max_hops = min(args.get("max_hops", 2), 3)
        from engine.knowledge.neo4j_client import get_neo4j_session

        pattern = f"(?i).*{name}.*"
        async with get_neo4j_session() as session:
            result = await session.run("""
                MATCH (e:Entity {kb_id: $kb_id})
                WHERE e.canonical_name =~ $pattern
                WITH e LIMIT 1
                MATCH (e)-[r]-(other:Entity {kb_id: $kb_id})
                RETURN e.canonical_name as source, type(r) as rel_type,
                       r.description as rel_desc,
                       other.canonical_name as target, other.entity_type as target_type
                ORDER BY type(r)
                LIMIT 30
            """, kb_id=self.kb_id, pattern=pattern)

            rels = [r async for r in result]

        if not rels:
            return ToolResult(content=f"No relationships found for entity matching '{name}'.")

        source = rels[0]["source"]
        lines = [f"Relationships for **{source}** ({len(rels)} connections):\n"]
        for r in rels:
            desc = f" — {r['rel_desc'][:100]}" if r['rel_desc'] else ""
            lines.append(f"- {source} --[{r['rel_type']}]--> {r['target']} ({r['target_type']}){desc}")
        return ToolResult(content="\n".join(lines), metadata={"count": len(rels)})

    async def _entity_path(self, args: dict) -> ToolResult:
        source = args.get("entity_name", "")
        target = args.get("target_entity", "")
        if not source or not target:
            return ToolResult(content="Error: entity_name and target_entity are required", is_error=True)

        from engine.knowledge.neo4j_client import get_neo4j_session

        source_pat = f"(?i).*{source}.*"
        target_pat = f"(?i).*{target}.*"

        async with get_neo4j_session() as session:
            result = await session.run("""
                MATCH (a:Entity {kb_id: $kb_id}), (b:Entity {kb_id: $kb_id})
                WHERE a.canonical_name =~ $source_pat AND b.canonical_name =~ $target_pat
                WITH a, b LIMIT 1
                MATCH path = shortestPath((a)-[*..5]-(b))
                RETURN [n IN nodes(path) | n.canonical_name] as nodes,
                       [r IN relationships(path) | type(r)] as rels
                LIMIT 1
            """, kb_id=self.kb_id, source_pat=source_pat, target_pat=target_pat)

            path = await result.single()

        if not path:
            return ToolResult(content=f"No path found between '{source}' and '{target}'.")

        nodes = path["nodes"]
        rels = path["rels"]
        chain_parts = []
        for i, node in enumerate(nodes):
            chain_parts.append(f"**{node}**")
            if i < len(rels):
                chain_parts.append(f" --[{rels[i]}]--> ")

        chain = "".join(chain_parts)
        return ToolResult(
            content=f"Shortest path ({len(nodes)} nodes, {len(rels)} hops):\n\n{chain}",
            metadata={"hops": len(rels), "nodes": nodes},
        )

    async def _entities_by_type(self, args: dict) -> ToolResult:
        entity_type = args.get("entity_type", "")
        from engine.knowledge.neo4j_client import get_neo4j_session

        if entity_type:
            async with get_neo4j_session() as session:
                result = await session.run("""
                    MATCH (e:Entity {kb_id: $kb_id, entity_type: $type})
                    RETURN e.canonical_name as name, e.description as desc,
                           e.mention_count as mentions
                    ORDER BY e.mention_count DESC
                    LIMIT 30
                """, kb_id=self.kb_id, type=entity_type)
                entities = [r async for r in result]
        else:
            async with get_neo4j_session() as session:
                result = await session.run("""
                    MATCH (e:Entity {kb_id: $kb_id})
                    RETURN e.entity_type as type, count(e) as cnt
                    ORDER BY cnt DESC
                """, kb_id=self.kb_id)
                types = [r async for r in result]

            if not types:
                return ToolResult(content="No entities in the knowledge graph.")

            lines = ["Entity types in knowledge graph:\n"]
            for t in types:
                lines.append(f"- {t['type']}: {t['cnt']} entities")
            lines.append("\nUse entity_type parameter to list entities of a specific type.")
            return ToolResult(content="\n".join(lines))

        if not entities:
            return ToolResult(content=f"No entities of type '{entity_type}' found.")

        lines = [f"Entities of type '{entity_type}' ({len(entities)}):\n"]
        for e in entities:
            lines.append(f"- **{e['name']}** ({e['mentions']} mentions): {(e['desc'] or '')[:120]}")
        return ToolResult(content="\n".join(lines), metadata={"count": len(entities)})

    async def _related_documents(self, args: dict) -> ToolResult:
        name = args.get("entity_name", "")
        if not name:
            return ToolResult(content="Error: entity_name is required", is_error=True)

        from engine.knowledge.neo4j_client import get_neo4j_session

        pattern = f"(?i).*{name}.*"
        async with get_neo4j_session() as session:
            result = await session.run("""
                MATCH (e:Entity {kb_id: $kb_id})
                WHERE e.canonical_name =~ $pattern
                RETURN e.canonical_name as name, e.source_doc_ids as doc_ids
                LIMIT 5
            """, kb_id=self.kb_id, pattern=pattern)

            entities = [r async for r in result]

        if not entities:
            return ToolResult(content=f"No entities matching '{name}' found.")

        all_doc_ids = set()
        for e in entities:
            if e["doc_ids"]:
                all_doc_ids.update(e["doc_ids"])

        lines = [f"Entity '{entities[0]['name']}' appears in {len(all_doc_ids)} document(s):\n"]
        for did in list(all_doc_ids)[:10]:
            lines.append(f"- Document ID: {did}")

        return ToolResult(content="\n".join(lines), metadata={"doc_ids": list(all_doc_ids)})
