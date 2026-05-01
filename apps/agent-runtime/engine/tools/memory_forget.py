"""Memory Forget tool — allows agents to delete persistent memories."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult


class MemoryForgetTool(BaseTool):
    name = "memory_forget"
    description = (
        "Delete a stored memory by key. Use this to remove outdated or "
        "incorrect information from the agent's persistent memory."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The memory key to delete",
            },
            "scope": {
                "type": "string",
                "enum": ["room", "hall", "wing"],
                "default": "room",
                "description": "Delete scope: single memory, category, or entire wing",
            },
            "wing": {
                "type": "string",
                "description": "Wing name (required for wing scope)",
            },
        },
        "required": ["key"],
    }

    def __init__(self, db_url: str = "", agent_id: str = "", tenant_id: str = ""):
        self._db_url = db_url
        self._agent_id = agent_id
        self._tenant_id = tenant_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        key = arguments["key"]

        try:
            import uuid as uuid_mod

            from sqlalchemy import delete
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

            engine = create_async_engine(self._db_url, echo=False)

            import sys
            from pathlib import Path

            sys.path.insert(
                0, str(Path(__file__).resolve().parents[3] / "packages" / "db")
            )
            from models.agent_memory import AgentMemory

            async with AsyncSession(engine, expire_on_commit=False) as db:
                result = await db.execute(
                    delete(AgentMemory).where(
                        AgentMemory.agent_id == uuid_mod.UUID(self._agent_id),
                        AgentMemory.tenant_id == uuid_mod.UUID(self._tenant_id),
                        AgentMemory.key == key,
                    )
                )
                deleted = result.rowcount

                # Also delete from MemPalace
                try:
                    from engine.memory.palace import MemoryPalace

                    palace = MemoryPalace(
                        db=db,
                        agent_id=uuid_mod.UUID(self._agent_id),
                        tenant_id=uuid_mod.UUID(self._tenant_id),
                    )
                    await palace.forget(
                        key=key,
                        wing_name=arguments.get("wing"),
                        scope=arguments.get("scope", "room"),
                    )
                except Exception:
                    pass  # MemPalace is optional enhancement

                await db.commit()

            await engine.dispose()

            if deleted:
                return ToolResult(content=f"Forgotten memory '{key}'.")
            else:
                return ToolResult(content=f"No memory found with key '{key}'.")
        except Exception as e:
            return ToolResult(content=f"Failed to forget memory: {e}", is_error=True)
