"""Source Watch tools: agents read watched sources, their retained snapshots and the changes between them."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from engine import credentials
from engine.tools.base import BaseTool, ConfigField, ToolResult

_SOURCE_ARG = {
    "type": "string",
    "description": "The source id, or its exact name, from source_list",
}


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None and hasattr(v, "isoformat") else None


def citation(src: Any, snap: Any) -> dict[str, Any]:
    fetched = _iso(snap.fetched_at)
    return {
        "source_id": str(src.id),
        "source": src.name,
        "url": snap.url,
        "title": snap.title,
        "fetched_at": fetched,
        "sha256": snap.content_sha256,
        "snapshot_id": str(snap.id),
        "cite_as": f"{src.name}, {snap.url}, retrieved {(fetched or '')[:10]} (snapshot sha256 {snap.content_sha256[:12]})",
    }


class _SourceTool(BaseTool):
    input_schema: dict[str, Any] = {"type": "object"}

    def __init__(
        self,
        tenant_id: str = "",
        execution_id: str = "",
        user_id: str = "",
        agent_name: str = "",
    ) -> None:
        self.tenant_id = tenant_id
        self._execution_id = execution_id
        self._user_id = user_id
        self._agent_name = agent_name

    def _tenant(self) -> str:
        return str(self.tenant_id or credentials.current_tenant() or "")

    @staticmethod
    def _ok(payload: Any, **meta: Any) -> ToolResult:
        return ToolResult(
            content=json.dumps(payload, default=str, ensure_ascii=False), metadata=meta
        )

    @staticmethod
    def _fail(message: str, **meta: Any) -> ToolResult:
        return ToolResult(content=message, is_error=True, metadata=meta)

    async def _run(self, fn) -> ToolResult:
        from engine.sources import db as sdb

        if not self._tenant():
            return self._fail("No tenant in context, watched sources cannot be read.")
        try:
            async with sdb.session() as s:
                return await fn(s)
        except LookupError as e:
            return self._fail(str(e))

    async def _source(self, s: Any, ref: Any) -> Any:
        from sqlalchemy import func, select

        from models.source_watch import WatchSource

        ref = str(ref or "").strip()
        if not ref:
            raise LookupError("Say which source. source_list shows them.")
        tenant = uuid.UUID(self._tenant())
        try:
            sid = uuid.UUID(ref)
        except ValueError:
            sid = None
        if sid is not None:
            row = (
                await s.execute(
                    select(WatchSource).where(
                        WatchSource.id == sid, WatchSource.tenant_id == tenant
                    )
                )
            ).scalar_one_or_none()
        else:
            row = (
                await s.execute(
                    select(WatchSource).where(
                        WatchSource.tenant_id == tenant,
                        func.lower(WatchSource.name) == ref.lower(),
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            raise LookupError(
                f"No watched source matches {ref!r}. source_list shows them."
            )
        return row


class SourceListTool(_SourceTool):
    name = "source_list"
    risk_tier = "low"
    description = (
        "List the authoritative sources this tenant watches for changes, such as policy and tariff pages, "
        "guidance PDFs, data files and feeds, with when each was last checked and last changed. "
        "Call this first to find a source id for source_snapshot_get, source_diff or source_check."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional words to match in the name or URL",
            },
            "jurisdiction": {
                "type": "string",
                "description": "Optional jurisdiction, such as EU",
            },
            "tag": {"type": "string", "description": "Optional tag"},
            "changed_since": {
                "type": "string",
                "description": "Optional ISO date. Only sources that changed on or after it.",
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from datetime import datetime

        from sqlalchemy import func, select

        from models.source_watch import SourceChange, WatchSource

        q = str(arguments.get("query") or "").strip().lower()
        jur = str(arguments.get("jurisdiction") or "").strip().lower()
        tag = str(arguments.get("tag") or "").strip().lower()
        since = None
        if arguments.get("changed_since"):
            try:
                since = datetime.fromisoformat(
                    str(arguments["changed_since"]).replace("Z", "+00:00")
                )
            except ValueError:
                return self._fail(
                    "changed_since must be an ISO date such as 2026-01-31."
                )

        async def go(s):
            tenant = uuid.UUID(self._tenant())
            rows = (
                (
                    await s.execute(
                        select(WatchSource)
                        .where(WatchSource.tenant_id == tenant)
                        .order_by(WatchSource.name)
                    )
                )
                .scalars()
                .all()
            )
            counts = dict(
                (
                    await s.execute(
                        select(SourceChange.source_id, func.count())
                        .where(SourceChange.tenant_id == tenant)
                        .group_by(SourceChange.source_id)
                    )
                ).all()
            )
            out = []
            for r in rows:
                if q and q not in r.name.lower() and q not in r.url.lower():
                    continue
                if jur and jur != (r.jurisdiction or "").lower():
                    continue
                if tag and tag not in [t.lower() for t in (r.tags or [])]:
                    continue
                if since is not None:
                    lc = r.last_changed_at
                    if lc is None:
                        continue
                    if since.tzinfo is None:
                        lc = lc.replace(tzinfo=None)
                    if lc < since:
                        continue
                out.append(
                    {
                        "id": str(r.id),
                        "name": r.name,
                        "url": r.url,
                        "kind": r.kind,
                        "jurisdiction": r.jurisdiction,
                        "tags": list(r.tags or []),
                        "risk_tier": r.risk_tier,
                        "active": bool(r.active),
                        "status": r.last_status,
                        "last_checked_at": _iso(r.last_checked_at),
                        "last_changed_at": _iso(r.last_changed_at),
                        "changes_recorded": int(counts.get(r.id, 0)),
                        "has_snapshot": r.current_snapshot_id is not None,
                    }
                )
            return self._ok({"sources": out, "count": len(out)})

        return await self._run(go)


class SourceSnapshotGetTool(_SourceTool):
    name = "source_snapshot_get"
    risk_tier = "low"
    description = (
        "Read the retained text of a watched source, the latest snapshot by default or a given one, "
        "with citation details (URL, retrieval time, SHA-256). Quote and cite from this rather than "
        "the live page, because snapshots never change. Long texts come in pages, use offset to continue."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source": _SOURCE_ARG,
            "snapshot_id": {
                "type": "string",
                "description": "Optional snapshot id. Without it the latest snapshot is used.",
            },
            "offset": {
                "type": "integer",
                "description": "Character offset to start from",
                "default": 0,
            },
            "max_chars": {
                "type": "integer",
                "description": "How many characters to return, up to 60000",
                "default": 20000,
            },
            "find": {
                "type": "string",
                "description": "Optional words to look for. The page returned starts a little before the first match.",
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from sqlalchemy import select

        from models.source_watch import SourceSnapshot, WatchSource

        try:
            offset = max(0, int(arguments.get("offset") or 0))
            size = min(60000, max(500, int(arguments.get("max_chars") or 20000)))
        except (TypeError, ValueError):
            return self._fail("offset and max_chars must be whole numbers.")
        find = str(arguments.get("find") or "").strip()

        async def go(s):
            tenant = uuid.UUID(self._tenant())
            snap_ref = str(arguments.get("snapshot_id") or "").strip()
            if snap_ref:
                try:
                    pid = uuid.UUID(snap_ref)
                except ValueError:
                    return self._fail("snapshot_id is not a valid id.")
                snap = (
                    await s.execute(
                        select(SourceSnapshot).where(
                            SourceSnapshot.id == pid, SourceSnapshot.tenant_id == tenant
                        )
                    )
                ).scalar_one_or_none()
                if snap is None:
                    return self._fail("No snapshot with that id in this tenant.")
                src = await s.get(WatchSource, snap.source_id)
            else:
                src = await self._source(s, arguments.get("source"))
                if src.current_snapshot_id is None:
                    return self._fail(
                        f"{src.name} has no snapshot yet. Its first check has not succeeded"
                        + (f": {src.last_error}" if src.last_error else ".")
                    )
                snap = await s.get(SourceSnapshot, src.current_snapshot_id)
            text = snap.normalized_text or ""
            start = offset
            if find:
                hit = text.lower().find(find.lower(), offset)
                if hit < 0:
                    return self._ok(
                        {
                            "found": False,
                            "message": f"{find!r} does not appear after offset {offset}.",
                            "citation": citation(src, snap),
                        }
                    )
                start = max(0, hit - 300)
            piece = text[start : start + size]
            end = start + len(piece)
            return self._ok(
                {
                    "citation": citation(src, snap),
                    "kind": snap.kind,
                    "parser_version": snap.parser_version,
                    "offset": start,
                    "next_offset": end if end < len(text) else None,
                    "total_chars": len(text),
                    "stored_text_truncated": bool(snap.text_truncated),
                    "text": piece,
                },
                source_id=str(src.id),
                snapshot_id=str(snap.id),
            )

        return await self._run(go)


class SourceDiffTool(_SourceTool):
    name = "source_diff"
    risk_tier = "low"
    description = (
        "Show what changed in a watched source: lines added and removed for text, or rows added, "
        "removed and changed for tables, with a summary, a materiality hint and citations for both "
        "snapshots. Give change_id, or a source to get its latest change and a list of earlier ones."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "change_id": {
                "type": "string",
                "description": "A change id, from a source.changed event or an earlier call",
            },
            "source": _SOURCE_ARG,
            "max_lines": {
                "type": "integer",
                "description": "How many changed lines or rows to return, up to 2000",
                "default": 400,
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from sqlalchemy import select

        from models.source_watch import SourceChange, SourceSnapshot, WatchSource

        try:
            limit = min(2000, max(10, int(arguments.get("max_lines") or 400)))
        except (TypeError, ValueError):
            return self._fail("max_lines must be a whole number.")

        async def go(s):
            tenant = uuid.UUID(self._tenant())
            ref = str(arguments.get("change_id") or "").strip()
            earlier: list[dict[str, Any]] = []
            if ref:
                try:
                    cid = uuid.UUID(ref)
                except ValueError:
                    return self._fail("change_id is not a valid id.")
                ch = (
                    await s.execute(
                        select(SourceChange).where(
                            SourceChange.id == cid, SourceChange.tenant_id == tenant
                        )
                    )
                ).scalar_one_or_none()
                if ch is None:
                    return self._fail("No change with that id in this tenant.")
                src = await s.get(WatchSource, ch.source_id)
            else:
                src = await self._source(s, arguments.get("source"))
                rows = (
                    (
                        await s.execute(
                            select(SourceChange)
                            .where(SourceChange.source_id == src.id)
                            .order_by(SourceChange.detected_at.desc())
                            .limit(11)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not rows:
                    return self._ok(
                        {
                            "source": src.name,
                            "changes": [],
                            "message": f"No change has been detected in {src.name} since it was first captured.",
                        }
                    )
                ch = rows[0]
                earlier = [
                    {
                        "change_id": str(c.id),
                        "detected_at": _iso(c.detected_at),
                        "summary": c.summary,
                        "materiality_hint": c.materiality_hint,
                    }
                    for c in rows[1:]
                ]
            before = (
                await s.get(SourceSnapshot, ch.from_snapshot_id)
                if ch.from_snapshot_id
                else None
            )
            after = await s.get(SourceSnapshot, ch.to_snapshot_id)
            d = dict(ch.diff or {})
            body: dict[str, Any] = {"kind": d.get("kind")}
            if d.get("kind") == "table":
                sheets = []
                budget = limit
                for sh in d.get("sheets") or []:
                    item = {
                        k: sh.get(k)
                        for k in ("name", "header", "key_column", "header_changed")
                    }
                    for k in ("added", "removed", "changed"):
                        rows_ = sh.get(k) or []
                        item[k] = rows_[: max(0, budget)]
                        budget -= len(item[k])
                    sheets.append(item)
                body["sheets"] = sheets
                body["clipped"] = budget < 0 or bool(d.get("truncated"))
            else:
                body["added"] = (d.get("added") or [])[:limit]
                body["removed"] = (d.get("removed") or [])[:limit]
                body["clipped"] = (
                    len(d.get("added") or []) > limit
                    or len(d.get("removed") or []) > limit
                    or bool(d.get("truncated"))
                )
            return self._ok(
                {
                    "change_id": str(ch.id),
                    "source": src.name if src else None,
                    "detected_at": _iso(ch.detected_at),
                    "summary": ch.summary,
                    "materiality_hint": ch.materiality_hint,
                    "stats": ch.stats,
                    "diff": body,
                    "before": citation(src, before) if before and src else None,
                    "after": citation(src, after) if after and src else None,
                    "earlier_changes": earlier,
                },
                change_id=str(ch.id),
            )

        return await self._run(go)


class SourceCheckTool(_SourceTool):
    name = "source_check"
    # makes an outbound request and may record a change that starts other work
    risk_tier = "medium"
    description = (
        "Ask for a watched source to be checked now instead of waiting for its schedule, and wait for "
        "the result: unchanged, changed (with a summary and change_id for source_diff) or an error. "
        "Paused sources are not checked, a person must resume them."
    )
    config_fields = tuple(
        ConfigField(
            key=f"SOURCE_AUTH_{i}",
            label=f"Source credential {i}",
            kind="secret",
            group="Source Watch",
            description=(
                "Sign-in for watched sources that need it. Either a token, sent as a Bearer "
                "Authorization header, or a full header such as 'X-Api-Key: abc'. Pick it on the "
                "source by this name. Only ever sent to the source's own host."
            ),
            dynamic=True,
        )
        for i in range(1, 6)
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source": _SOURCE_ARG,
            "wait_seconds": {
                "type": "integer",
                "description": "How long to wait for the result, up to 120",
                "default": 60,
            },
        },
        "required": ["source"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from sqlalchemy import func, select, update

        from engine import governance
        from models.source_watch import SourceChange, WatchSource

        try:
            wait = min(120, max(5, int(arguments.get("wait_seconds") or 60)))
        except (TypeError, ValueError):
            return self._fail("wait_seconds must be a whole number.")

        async def go(s):
            src = await self._source(s, arguments.get("source"))
            if not src.active:
                return self._fail(
                    f"{src.name} is paused"
                    + (f" ({src.paused_reason})" if src.paused_reason else "")
                    + ". A person must resume it on the Sources page."
                )
            await governance.ensure_fresh()
            hit = governance.stopped(src.tenant_id, "source", str(src.id))
            if hit:
                return self._fail(
                    f"{src.name} is stopped by a kill switch"
                    + (f": {hit[2]}" if hit[2] else "")
                    + "."
                )
            before = src.check_count or 0
            sid = src.id
            await s.execute(
                update(WatchSource)
                .where(WatchSource.id == sid)
                .values(next_check_at=func.now())
            )
            await s.commit()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + wait
            while loop.time() < deadline:
                await asyncio.sleep(2)
                row = (
                    await s.execute(
                        select(
                            WatchSource.check_count,
                            WatchSource.last_status,
                            WatchSource.last_error,
                            WatchSource.last_checked_at,
                            WatchSource.current_snapshot_id,
                        ).where(WatchSource.id == sid)
                    )
                ).first()
                await s.commit()
                if row is None:
                    return self._fail(
                        "The source was deleted while it was being checked."
                    )
                if (row.check_count or 0) > before:
                    out: dict[str, Any] = {
                        "source": src.name,
                        "status": row.last_status,
                        "checked_at": _iso(row.last_checked_at),
                        "snapshot_id": (
                            str(row.current_snapshot_id)
                            if row.current_snapshot_id
                            else None
                        ),
                    }
                    if row.last_status == "error":
                        out["error"] = row.last_error
                    if row.last_status == "changed":
                        ch = (
                            await s.execute(
                                select(SourceChange)
                                .where(SourceChange.source_id == sid)
                                .order_by(SourceChange.detected_at.desc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if ch is not None:
                            out.update(
                                change_id=str(ch.id),
                                summary=ch.summary,
                                materiality_hint=ch.materiality_hint,
                                next_step="Call source_diff with this change_id to see what changed.",
                            )
                    return self._ok(out, source_id=str(sid))
            return self._ok(
                {
                    "source": src.name,
                    "status": "queued",
                    "message": f"The check is queued but had not finished after {wait} seconds. Call source_list later to see the result.",
                },
                source_id=str(sid),
            )

        return await self._run(go)


SOURCE_TOOLS = {
    t.name: t
    for t in (SourceListTool, SourceSnapshotGetTool, SourceDiffTool, SourceCheckTool)
}
