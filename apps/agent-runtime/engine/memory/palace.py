"""MemoryPalace — Hierarchical AI memory with AAAK compression."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MemoryPalace:
    """Orchestrates hierarchical memory operations."""

    def __init__(self, db: AsyncSession, agent_id: uuid.UUID, tenant_id: uuid.UUID):
        self.db = db
        self.agent_id = agent_id
        self.tenant_id = tenant_id

    async def store(
        self,
        content: str,
        key: str | None = None,
        wing_name: str = "general",
        hall_type: str = "factual",
        importance: int = 5,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Store a memory in the palace hierarchy with AAAK compression."""
        from models.memory_palace import MemoryWing, MemoryHall, MemoryRoom, MemoryDrawer, HallType

        # Find or create wing
        result = await self.db.execute(
            select(MemoryWing).where(
                MemoryWing.agent_id == self.agent_id,
                MemoryWing.tenant_id == self.tenant_id,
                MemoryWing.name == wing_name,
            )
        )
        wing = result.scalar_one_or_none()
        if not wing:
            wing = MemoryWing(
                id=uuid.uuid4(),
                agent_id=self.agent_id,
                tenant_id=self.tenant_id,
                name=wing_name,
            )
            self.db.add(wing)
            await self.db.flush()

        # Find or create hall
        try:
            ht = HallType(hall_type)
        except ValueError:
            ht = HallType.FACTUAL

        result = await self.db.execute(
            select(MemoryHall).where(
                MemoryHall.wing_id == wing.id,
                MemoryHall.hall_type == ht,
            )
        )
        hall = result.scalar_one_or_none()
        if not hall:
            hall = MemoryHall(
                id=uuid.uuid4(),
                wing_id=wing.id,
                name=f"{wing_name} — {hall_type}",
                hall_type=ht,
            )
            self.db.add(hall)
            await self.db.flush()

        # Compress with AAAK
        from engine.memory.aaak_compressor import compress_to_aaak
        aaak_summary = await compress_to_aaak(content)

        # Find or create room (upsert by key/name)
        room_name = key or content[:100]
        result = await self.db.execute(
            select(MemoryRoom).where(
                MemoryRoom.hall_id == hall.id,
                MemoryRoom.name == room_name,
            )
        )
        room = result.scalar_one_or_none()
        if room:
            room.full_content = content
            room.summary_aaak = aaak_summary
            room.importance = max(room.importance, importance)
            room.access_count += 1
        else:
            room = MemoryRoom(
                id=uuid.uuid4(),
                hall_id=hall.id,
                name=room_name,
                summary_aaak=aaak_summary,
                full_content=content,
                importance=importance,
            )
            self.db.add(room)
            await self.db.flush()

        # Store original in drawer
        drawer = MemoryDrawer(
            id=uuid.uuid4(),
            room_id=room.id,
            content=content,
            source=source,
        )
        self.db.add(drawer)
        await self.db.flush()

        return {
            "status": "stored",
            "wing": wing_name,
            "hall": hall_type,
            "room": room_name,
            "compressed_length": len(aaak_summary),
            "original_length": len(content),
            "compression_ratio": f"{len(content) / max(len(aaak_summary), 1):.1f}x",
        }

    async def recall(
        self,
        query: str | None = None,
        key: str | None = None,
        wing_name: str | None = None,
        hall_type: str | None = None,
        mode: str = "exact",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Recall memories from the palace."""
        from models.memory_palace import MemoryWing, MemoryHall, MemoryRoom

        query_stmt = select(MemoryRoom).join(MemoryHall).join(MemoryWing).where(
            MemoryWing.agent_id == self.agent_id,
            MemoryWing.tenant_id == self.tenant_id,
        )

        if wing_name:
            query_stmt = query_stmt.where(MemoryWing.name == wing_name)
        if hall_type:
            from models.memory_palace import HallType
            try:
                query_stmt = query_stmt.where(MemoryHall.hall_type == HallType(hall_type))
            except ValueError:
                pass

        if key:
            query_stmt = query_stmt.where(MemoryRoom.name == key)
        elif query and mode == "search":
            query_stmt = query_stmt.where(
                MemoryRoom.full_content.ilike(f"%{query}%")
                | MemoryRoom.name.ilike(f"%{query}%")
            )

        query_stmt = query_stmt.order_by(
            MemoryRoom.importance.desc(),
            MemoryRoom.updated_at.desc(),
        ).limit(limit)

        result = await self.db.execute(query_stmt)
        rooms = result.scalars().all()

        # Increment access counts
        for room in rooms:
            room.access_count += 1
        await self.db.flush()

        return [
            {
                "key": room.name,
                "content": room.full_content,
                "summary_aaak": room.summary_aaak,
                "importance": room.importance,
                "access_count": room.access_count,
                "wing": wing_name or "general",
                "hall_type": hall_type or "factual",
                "updated_at": room.updated_at.isoformat() if room.updated_at else None,
            }
            for room in rooms
        ]

    async def get_context_window(self) -> str:
        """Get L0 + L1 context (always loaded, ~170 tokens)."""
        from models.memory_palace import MemoryWing, MemoryHall, MemoryRoom

        # Get top-importance rooms across all wings, compressed
        result = await self.db.execute(
            select(MemoryRoom.summary_aaak)
            .join(MemoryHall)
            .join(MemoryWing)
            .where(
                MemoryWing.agent_id == self.agent_id,
                MemoryWing.tenant_id == self.tenant_id,
                MemoryRoom.importance >= 7,  # Only high-importance memories
            )
            .order_by(MemoryRoom.importance.desc(), MemoryRoom.access_count.desc())
            .limit(10)
        )
        summaries = [row[0] for row in result.all() if row[0]]

        if not summaries:
            return ""

        return "MEMORY_CONTEXT:\n" + "\n".join(summaries)

    async def forget(
        self,
        key: str | None = None,
        wing_name: str | None = None,
        scope: str = "room",
    ) -> dict[str, int]:
        """Forget memories with cascading delete.

        Scopes: room (single memory), hall (category), wing (entire topic)
        """
        from models.memory_palace import MemoryWing, MemoryHall, MemoryRoom
        from sqlalchemy import delete

        deleted = 0

        if scope == "wing" and wing_name:
            result = await self.db.execute(
                delete(MemoryWing).where(
                    MemoryWing.agent_id == self.agent_id,
                    MemoryWing.tenant_id == self.tenant_id,
                    MemoryWing.name == wing_name,
                )
            )
            deleted = result.rowcount
        elif scope == "room" and key:
            result = await self.db.execute(
                delete(MemoryRoom).where(
                    MemoryRoom.name == key,
                    MemoryRoom.hall_id.in_(
                        select(MemoryHall.id).join(MemoryWing).where(
                            MemoryWing.agent_id == self.agent_id,
                            MemoryWing.tenant_id == self.tenant_id,
                        )
                    ),
                )
            )
            deleted = result.rowcount

        await self.db.flush()
        return {"deleted": deleted, "scope": scope}

    async def get_stats(self) -> dict[str, Any]:
        """Get memory palace statistics."""
        from models.memory_palace import MemoryWing, MemoryHall, MemoryRoom

        wings_count = await self.db.scalar(
            select(func.count()).select_from(MemoryWing).where(
                MemoryWing.agent_id == self.agent_id,
            )
        )
        rooms_count = await self.db.scalar(
            select(func.count()).select_from(MemoryRoom)
            .join(MemoryHall).join(MemoryWing)
            .where(MemoryWing.agent_id == self.agent_id)
        )

        return {
            "wings": wings_count or 0,
            "rooms": rooms_count or 0,
            "agent_id": str(self.agent_id),
        }
