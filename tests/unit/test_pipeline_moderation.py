"""Pipeline runs pass the tenant moderation gate before they start, like agent runs."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())


def _ctx(gate=True):
    c = MagicMock()
    c.gate = object() if gate else None
    return c


def test_blocked_input_is_refused_before_the_run():
    from app.routers import agents
    from engine.moderation_gate import ModerationBlocked

    decision = SimpleNamespace(reason="pii")

    async def block(content, **kw):
        raise ModerationBlocked(decision, source="pre_llm", content_preview=content)

    body = SimpleNamespace(context={})
    with patch(
        "app.core.moderation_glue.build_gate_context", AsyncMock(return_value=_ctx())
    ), patch("app.core.moderation_glue.persist_events", AsyncMock()) as persist, patch(
        "engine.moderation_gate.check", block
    ):
        out = asyncio.run(
            agents._moderate_pipeline_input(
                MagicMock(), _user(), body, "SSN 987-12-3456"
            )
        )
    assert out.status_code == 422
    assert json.loads(out.body)["error"]["error_code"] == "MODERATION_BLOCKED"
    persist.assert_awaited_once()


def test_redaction_reaches_the_message_and_text_inputs():
    from app.routers import agents

    async def redact(content, **kw):
        return content.replace("987-12-3456", "***"), SimpleNamespace(action="redact")

    body = SimpleNamespace(context={"note": "SSN 987-12-3456", "weight": 51})
    with patch(
        "app.core.moderation_glue.build_gate_context", AsyncMock(return_value=_ctx())
    ), patch("app.core.moderation_glue.persist_events", AsyncMock()), patch(
        "engine.moderation_gate.check", redact
    ):
        out = asyncio.run(
            agents._moderate_pipeline_input(
                MagicMock(), _user(), body, "id 987-12-3456"
            )
        )
    assert out == "id ***"


def test_no_policy_leaves_input_alone():
    from app.routers import agents

    body = SimpleNamespace(context={"a": "b"})
    with patch(
        "app.core.moderation_glue.build_gate_context",
        AsyncMock(return_value=_ctx(gate=False)),
    ):
        out = asyncio.run(
            agents._moderate_pipeline_input(MagicMock(), _user(), body, "hello")
        )
    assert out is None


def test_allowed_input_is_one_check_and_events_are_committed_on_block():
    from app.routers import agents
    from engine.moderation_gate import ModerationBlocked

    calls = []

    async def allow(content, **kw):
        calls.append(content)
        return content, SimpleNamespace(action="allow")

    body = SimpleNamespace(context={"a": "one", "b": "two", "n": 3})
    db = MagicMock()
    db.commit = AsyncMock()
    with patch(
        "app.core.moderation_glue.build_gate_context", AsyncMock(return_value=_ctx())
    ), patch("app.core.moderation_glue.persist_events", AsyncMock()), patch(
        "engine.moderation_gate.check", allow
    ):
        out = asyncio.run(agents._moderate_pipeline_input(db, _user(), body, "hello"))
    assert out == "hello" and len(calls) == 1
    assert calls[0] == "hello"

    async def block(content, **kw):
        raise ModerationBlocked(
            SimpleNamespace(reason="r", acted_categories=["x"]),
            source="pre_llm",
            content_preview="",
        )

    db.commit.reset_mock()
    with patch(
        "app.core.moderation_glue.build_gate_context", AsyncMock(return_value=_ctx())
    ), patch("app.core.moderation_glue.persist_events", AsyncMock()), patch(
        "engine.moderation_gate.check", block
    ):
        out = asyncio.run(agents._moderate_pipeline_input(db, _user(), body, "hello"))
    assert out.status_code == 422
    db.commit.assert_awaited_once()
