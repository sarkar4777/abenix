"""Who sees which broker connection, and so which machines, and who may command them.

A connection with no team belongs to the whole workspace. One with a team (a
permission set) is seen by that team's members, its creator, admins and people
holding telemetry.manage, plus anyone it is shared with through ResourceShare.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import capabilities_for, holds
from app.core.permissions import is_admin
from models.governance import PermissionAssignment, PermissionSet
from models.resource_share import ResourceShare, SharePermission
from models.telemetry import TelemetryConnection
from models.user import User

KIND = "telemetry_connection"
_TTL = 5.0
_cache: dict[Any, tuple[float, "Scope"]] = {}


@dataclass
class Scope:
    everything: bool
    visible: set[str]
    commandable: set[str]
    teams: dict[str, str]
    connections: list[Any]

    def sees(self, conn_id: str | None) -> bool:
        if self.everything:
            return True
        return bool(conn_id) and conn_id in self.visible

    def may_command(self, conn_id: str | None) -> bool:
        if self.everything:
            return True
        return bool(conn_id) and conn_id in self.commandable


def api_key_grants(user: Any, cap: str) -> bool:
    """An API key's scopes can carry a capability, as a list or under allowed_actions or capabilities."""
    scopes = getattr(user, "_api_key_scopes", None)
    if not scopes:
        return False
    vals: list[Any] = []
    if isinstance(scopes, list):
        vals = scopes
    elif isinstance(scopes, dict):
        for k in ("allowed_actions", "capabilities"):
            v = scopes.get(k)
            if isinstance(v, list):
                vals.extend(v)
        if scopes.get(cap) is True:
            return True
    return any(isinstance(v, str) and holds(frozenset({v}), cap) for v in vals)


async def has(db: AsyncSession, user: Any, cap: str) -> bool:
    if api_key_grants(user, cap):
        return True
    return holds(await capabilities_for(db, user), cap)


async def scope_for(db: AsyncSession, user: User, *, fresh: bool = False) -> Scope:
    key = (user.id, getattr(user, "_api_key_id", None))
    hit = _cache.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    conns = (
        (
            await db.execute(
                select(TelemetryConnection)
                .where(TelemetryConnection.tenant_id == user.tenant_id)
                .order_by(TelemetryConnection.name)
            )
        )
        .scalars()
        .all()
    )
    team_ids = {c.team_id for c in conns if c.team_id}
    teams: dict[str, str] = {}
    if team_ids:
        for tid, name in (
            await db.execute(
                select(PermissionSet.id, PermissionSet.name).where(
                    PermissionSet.id.in_(team_ids)
                )
            )
        ).all():
            teams[str(tid)] = name
    everything = is_admin(user) or await has(db, user, "telemetry.manage")
    visible: set[str] = set()
    commandable: set[str] = set()
    if not everything:
        mine = {
            r[0]
            for r in (
                await db.execute(
                    select(PermissionAssignment.permission_set_id).where(
                        PermissionAssignment.user_id == user.id,
                        PermissionAssignment.tenant_id == user.tenant_id,
                    )
                )
            ).all()
        }
        shares: dict[uuid.UUID, Any] = {}
        for rid, perm in (
            await db.execute(
                select(ResourceShare.resource_id, ResourceShare.permission).where(
                    ResourceShare.shared_with_user_id == user.id,
                    ResourceShare.resource_type == KIND,
                    ResourceShare.live(),
                )
            )
        ).all():
            shares[rid] = perm
        for c in conns:
            cid = str(c.id)
            own = c.team_id is None or c.team_id in mine or c.created_by == user.id
            share = shares.get(c.id)
            if own or share is not None:
                visible.add(cid)
            if own or share in (SharePermission.EXECUTE, SharePermission.EDIT):
                commandable.add(cid)
    sc = Scope(
        everything=everything,
        visible=visible,
        commandable=commandable,
        teams=teams,
        connections=list(conns),
    )
    _cache[key] = (time.monotonic(), sc)
    return sc


def forget(user_id: Any = None) -> None:
    if user_id is None:
        _cache.clear()
        return
    for k in [k for k in _cache if k[0] == user_id]:
        _cache.pop(k, None)


async def share_counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[str, int]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ResourceShare.resource_id, func.count())
            .where(
                ResourceShare.resource_type == KIND,
                ResourceShare.resource_id.in_(ids),
                ResourceShare.live(),
            )
            .group_by(ResourceShare.resource_id)
        )
    ).all()
    return {str(r[0]): int(r[1]) for r in rows}


async def can_share(db: AsyncSession, user: User, conn_id: uuid.UUID) -> bool:
    c = (
        await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.id == conn_id,
                TelemetryConnection.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if c is None:
        return False
    return (
        c.created_by == user.id
        or is_admin(user)
        or await has(db, user, "telemetry.manage")
    )
