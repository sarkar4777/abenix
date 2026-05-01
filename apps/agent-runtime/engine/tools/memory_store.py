"""Memory Store tool — allows agents to persist information across executions."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult


class MemoryStoreTool(BaseTool):
    name = "memory_store"
    description = (
        "Store a piece of information in persistent memory. Use this to remember "
        "facts, procedures, or past events across conversations. Memories are "
        "scoped to this agent and persist until explicitly forgotten."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "A short, descriptive key for the memory (e.g., 'user_preferred_format', 'last_migration_status')",
            },
            "value": {
                "type": "string",
                "description": "The information to remember",
            },
            "memory_type": {
                "type": "string",
                "enum": ["factual", "procedural", "episodic"],
                "description": "Type of memory: factual (facts), procedural (how-to), episodic (past events)",
                "default": "factual",
            },
            "importance": {
                "type": "integer",
                "description": "Importance level 1-10 (higher = more important, retrieved first)",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
            },
            "wing": {
                "type": "string",
                "description": "Memory wing/category (e.g., 'project-alpha', 'user-preferences')",
                "default": "general",
            },
            "hall_type": {
                "type": "string",
                "enum": ["factual", "procedural", "episodic", "emotional", "decision"],
                "default": "factual",
            },
        },
        "required": ["key", "value"],
    }

    def __init__(self, db_url: str = "", agent_id: str = "", tenant_id: str = ""):
        self._db_url = db_url
        self._agent_id = agent_id
        self._tenant_id = tenant_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments["key"]
        value = arguments["value"]
        memory_type = arguments.get("memory_type", "factual")
        importance = min(max(arguments.get("importance", 5), 1), 10)

        try:
            import uuid as uuid_mod

            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

            engine = create_async_engine(self._db_url, echo=False)

            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
            from models.agent_memory import AgentMemory, MemoryType

            async with AsyncSession(engine, expire_on_commit=False) as db:
                # Upsert: check if key exists for this agent
                result = await db.execute(
                    select(AgentMemory).where(
                        AgentMemory.agent_id == uuid_mod.UUID(self._agent_id),
                        AgentMemory.tenant_id == uuid_mod.UUID(self._tenant_id),
                        AgentMemory.key == key,
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.value = value
                    existing.memory_type = MemoryType(memory_type)
                    existing.importance = importance
                    existing.access_count = (existing.access_count or 0) + 1
                else:
                    memory = AgentMemory(
                        agent_id=uuid_mod.UUID(self._agent_id),
                        tenant_id=uuid_mod.UUID(self._tenant_id),
                        key=key,
                        value=value,
                        memory_type=MemoryType(memory_type),
                        importance=importance,
                    )
                    db.add(memory)

                await db.commit()

                # Also store in MemPalace hierarchy (enhanced memory)
                try:
                    from engine.memory.palace import MemoryPalace
                    palace = MemoryPalace(db=db, agent_id=uuid_mod.UUID(self._agent_id), tenant_id=uuid_mod.UUID(self._tenant_id))
                    await palace.store(
                        content=value,
                        key=key,
                        wing_name=arguments.get("wing", "general"),
                        hall_type=arguments.get("hall_type", memory_type),
                        importance=importance,
                    )
                except Exception:
                    pass  # MemPalace is optional enhancement

                await db.commit()

            await engine.dispose()
            action = "Updated" if existing else "Stored"
            return ToolResult(
                content=f"{action} memory '{key}' ({memory_type}, importance={importance})",
                metadata={"key": key, "action": action.lower()},
            )
        except Exception as e:
            return ToolResult(content=f"Failed to store memory: {e}", is_error=True)
