"""Memory Recall tool — allows agents to retrieve persistent memories."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult


class MemoryRecallTool(BaseTool):
    name = "memory_recall"
    description = (
        "Retrieve stored memories. Search by key, type, or get all memories "
        "sorted by importance. Use this at the start of conversations to "
        "recall context from previous interactions."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Exact key to retrieve (optional — omit for search)",
            },
            "search": {
                "type": "string",
                "description": "Search term to find matching memories by key or value",
            },
            "memory_type": {
                "type": "string",
                "enum": ["factual", "procedural", "episodic"],
                "description": "Filter by memory type",
            },
            "limit": {
                "type": "integer",
                "description": "Max memories to return (default 10)",
                "default": 10,
            },
            "mode": {
                "type": "string",
                "enum": ["exact", "search", "semantic"],
                "default": "search",
                "description": "Recall mode: exact key lookup, text search, or semantic similarity",
            },
            "wing": {
                "type": "string",
                "description": "Filter by memory wing",
            },
        },
    }

    def __init__(self, db_url: str = "", agent_id: str = "", tenant_id: str = ""):
        self._db_url = db_url
        self._agent_id = agent_id
        self._tenant_id = tenant_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments.get("key")
        search = arguments.get("search")
        memory_type = arguments.get("memory_type")
        limit = min(arguments.get("limit", 10), 50)

        # Try MemPalace enhanced recall
        try:
            import uuid as uuid_mod

            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

            palace_engine = create_async_engine(self._db_url, echo=False)
            async with AsyncSession(palace_engine, expire_on_commit=False) as palace_db:
                from engine.memory.palace import MemoryPalace
                palace = MemoryPalace(db=palace_db, agent_id=uuid_mod.UUID(self._agent_id), tenant_id=uuid_mod.UUID(self._tenant_id))
                palace_results = await palace.recall(
                    query=search, key=key,
                    wing_name=arguments.get("wing"),
                    mode=arguments.get("mode", "search"),
                    limit=limit,
                )
                if palace_results:
                    # Prepend context window
                    context = await palace.get_context_window()
                    lines = []
                    if context:
                        lines.append(context)
                        lines.append("")
                    for m in palace_results:
                        lines.append(f"[{m.get('hall_type', 'factual')}] {m['key']} (importance={m['importance']}): {m['content']}")
                    await palace_db.commit()
                    await palace_engine.dispose()
                    return ToolResult(content="\n".join(lines))
                await palace_db.commit()
            await palace_engine.dispose()
        except Exception:
            pass  # Fall back to basic recall

        try:
            import uuid as uuid_mod

            from sqlalchemy import select, or_
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

            engine = create_async_engine(self._db_url, echo=False)

            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
            from models.agent_memory import AgentMemory, MemoryType

            async with AsyncSession(engine, expire_on_commit=False) as db:
                query = select(AgentMemory).where(
                    AgentMemory.agent_id == uuid_mod.UUID(self._agent_id),
                    AgentMemory.tenant_id == uuid_mod.UUID(self._tenant_id),
                )

                if key:
                    query = query.where(AgentMemory.key == key)
                if memory_type:
                    query = query.where(AgentMemory.memory_type == MemoryType(memory_type))
                if search:
                    pattern = f"%{search}%"
                    query = query.where(
                        or_(
                            AgentMemory.key.ilike(pattern),
                            AgentMemory.value.ilike(pattern),
                        )
                    )

                query = query.order_by(
                    AgentMemory.importance.desc(),
                    AgentMemory.updated_at.desc(),
                ).limit(limit)

                result = await db.execute(query)
                memories = result.scalars().all()

                # Update access count
                for mem in memories:
                    mem.access_count = (mem.access_count or 0) + 1
                await db.commit()

            await engine.dispose()

            if not memories:
                return ToolResult(content="No memories found.")

            lines = []
            for m in memories:
                type_label = m.memory_type.value if hasattr(m.memory_type, "value") else str(m.memory_type)
                lines.append(
                    f"[{type_label}] {m.key} (importance={m.importance}): {m.value}"
                )

            return ToolResult(
                content=f"Found {len(memories)} memories:\n" + "\n".join(lines),
                metadata={"count": len(memories)},
            )
        except Exception as e:
            return ToolResult(content=f"Failed to recall memories: {e}", is_error=True)
