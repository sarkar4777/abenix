"""Source Watch tools: registration, risk tiers, citations, paging, diffs and refusals."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# the runtime image has packages/db on PYTHONPATH, a bare checkout does not
_DB = str(Path(__file__).resolve().parents[3] / "packages" / "db")
if _DB not in sys.path:
    sys.path.append(_DB)

from engine import governance  # noqa: E402
from engine.tools import source_tools as T  # noqa: E402

TENANT = str(uuid.uuid4())


def _src(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT),
        name="Carrier tariff page",
        url="https://example.test/tariff",
        active=True,
        paused_reason=None,
        current_snapshot_id=uuid.uuid4(),
        last_error=None,
        check_count=3,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _snap(text="", **kw):
    base = dict(
        id=uuid.uuid4(),
        url="https://example.test/tariff",
        title="Tariff",
        fetched_at=datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc),
        content_sha256="f" * 64,
        normalized_text=text,
        text_truncated=False,
        kind="html",
        parser_version="sw-1",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FakeSession:
    def __init__(self, objects=None, results=None):
        self.objects = objects or {}
        self.results = list(results or [])

    async def get(self, model, key):
        return self.objects.get(key)

    async def execute(self, stmt):
        v = self.results.pop(0) if self.results else None
        return SimpleNamespace(
            scalar_one_or_none=lambda: v,
            scalars=lambda: SimpleNamespace(all=lambda: v or []),
        )

    async def commit(self):
        return None


def _patch_session(monkeypatch, session):
    from engine.sources import db as sdb

    @asynccontextmanager
    async def fake():
        yield session

    monkeypatch.setattr(sdb, "session", fake)


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_tools_declare_tiers_and_are_registered():
    from engine.agent_executor import _CONTEXT_TOOL_FACTORIES, _ensure_tool_classes

    _ensure_tool_classes()
    for name, cls in T.SOURCE_TOOLS.items():
        assert "risk_tier" in cls.__dict__
        assert _CONTEXT_TOOL_FACTORIES.get(name) is cls
    assert T.SourceCheckTool.risk_tier == "medium"
    assert T.SourceListTool.risk_tier == "low"
    assert {f.key for f in T.SourceCheckTool.config_fields} == {
        f"SOURCE_AUTH_{i}" for i in range(1, 6)
    }


def test_no_tenant_is_refused():
    r = _run(T.SourceListTool(tenant_id=""), {})
    assert r.is_error and "tenant" in r.content


def test_snapshot_get_pages_and_cites(monkeypatch):
    src = _src()
    snap = _snap(
        "A" * 1000 + "The declarant shall report." + "B" * 1000,
        id=src.current_snapshot_id,
    )
    _patch_session(monkeypatch, FakeSession({snap.id: snap}, results=[src]))
    r = _run(
        T.SourceSnapshotGetTool(tenant_id=TENANT),
        {"source": str(src.id), "max_chars": 600},
    )
    out = json.loads(r.content)
    assert not r.is_error
    assert out["citation"]["sha256"] == snap.content_sha256
    assert out["citation"]["cite_as"].startswith(
        "Carrier tariff page, https://example.test/tariff, retrieved 2026-10-01"
    )
    assert len(out["text"]) == 600 and out["next_offset"] == 600

    _patch_session(monkeypatch, FakeSession({snap.id: snap}, results=[src]))
    out = json.loads(
        _run(
            T.SourceSnapshotGetTool(tenant_id=TENANT),
            {"source": str(src.id), "find": "declarant"},
        ).content
    )
    assert "The declarant shall report." in out["text"] and out["offset"] == 704


def test_snapshot_get_without_a_snapshot_explains(monkeypatch):
    src = _src(current_snapshot_id=None, last_error="The site answered HTTP 503.")
    _patch_session(monkeypatch, FakeSession(results=[src]))
    r = _run(
        T.SourceSnapshotGetTool(tenant_id=TENANT), {"source": "Carrier tariff page"}
    )
    assert r.is_error and "503" in r.content


def test_unknown_source_names_the_next_step(monkeypatch):
    _patch_session(monkeypatch, FakeSession(results=[None]))
    r = _run(T.SourceDiffTool(tenant_id=TENANT), {"source": "nothing"})
    assert r.is_error and "source_list" in r.content


def test_diff_returns_lines_and_both_citations(monkeypatch):
    src = _src()
    before, after = _snap("old"), _snap("new", content_sha256="a" * 64)
    ch = SimpleNamespace(
        id=uuid.uuid4(),
        source_id=src.id,
        from_snapshot_id=before.id,
        to_snapshot_id=after.id,
        detected_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        summary="1 line added and 1 removed.",
        materiality_hint="medium",
        stats={"added": 1, "removed": 1},
        diff={"kind": "text", "added": ["new"], "removed": ["old"], "truncated": False},
    )
    _patch_session(
        monkeypatch,
        FakeSession({src.id: src, before.id: before, after.id: after}, results=[ch]),
    )
    out = json.loads(
        _run(T.SourceDiffTool(tenant_id=TENANT), {"change_id": str(ch.id)}).content
    )
    assert out["diff"]["added"] == ["new"] and out["diff"]["removed"] == ["old"]
    assert out["before"]["snapshot_id"] == str(before.id)
    assert out["after"]["sha256"] == "a" * 64
    assert out["materiality_hint"] == "medium"


def test_check_refuses_paused_and_stopped_sources(monkeypatch):
    paused = _src(active=False, paused_reason="Paused after 5 failed checks")
    _patch_session(monkeypatch, FakeSession(results=[paused]))
    r = _run(T.SourceCheckTool(tenant_id=TENANT), {"source": str(paused.id)})
    assert r.is_error and "paused" in r.content and "resume" in r.content

    src = _src()
    governance.load_for_test(switches=[(TENANT, "source", str(src.id), "legal hold")])
    try:
        _patch_session(monkeypatch, FakeSession(results=[src]))
        r = _run(T.SourceCheckTool(tenant_id=TENANT), {"source": str(src.id)})
        assert r.is_error and "kill switch" in r.content and "legal hold" in r.content
    finally:
        governance.load_for_test()
