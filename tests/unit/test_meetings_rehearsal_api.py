"""Meeting routes: rehearsal, readiness, decision mirror and the saved history."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _body(resp):
    return json.loads(resp.body)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())


def _meeting(**kw):
    base = dict(
        id=uuid.uuid4(),
        status="authorized",
        provider="livekit",
        room="af-room",
        scope_allow=["roadmap"],
        scope_defer=["pricing"],
        persona_scopes=["self"],
        display_name="Rep",
        agent_id=None,
        summary=None,
        notes=None,
        transcript_count=0,
        decision_count=0,
        started_at=None,
        ended_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FakeRedis:
    def __init__(self):
        self.kv, self.h, self.l = {}, {}, {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None):
        self.kv[k] = v

    async def hset(self, k, mapping):
        self.h.setdefault(k, {}).update({a: str(b) for a, b in mapping.items()})

    async def hget(self, k, f):
        return self.h.get(k, {}).get(f)

    async def hgetall(self, k):
        return dict(self.h.get(k, {}))

    async def exists(self, k):
        return int(k in self.h)

    async def expire(self, k, s):
        return True

    async def rpush(self, k, v):
        self.l.setdefault(k, []).append(v)

    async def lrange(self, k, a, b):
        return list(self.l.get(k, []))

    async def llen(self, k):
        return len(self.l.get(k, []))

    async def publish(self, ch, msg):
        self.kv.setdefault("_pub", []).append((ch, msg))

    async def aclose(self):
        return None


def test_readiness_names_what_is_missing_without_values():
    from app.routers.meetings import readiness_report

    r = readiness_report({"LIVEKIT_URL": "ws://x"}, is_admin=True)
    assert r["livekit_ready"] is False
    assert r["missing"] == ["LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    assert r["stt_ready"] is False and "OpenAI" in r["stt_message"]
    assert r["tts_ready"] is False
    assert "ws://x" not in json.dumps(r)

    ok = readiness_report(
        {
            "LIVEKIT_URL": "u",
            "LIVEKIT_API_KEY": "k",
            "LIVEKIT_API_SECRET": "s",
            "ELEVENLABS_API_KEY": "e",
        },
        is_admin=False,
    )
    assert ok["livekit_ready"] and ok["tts_ready"] and not ok["stt_ready"]
    assert ok["configure_url"] is None


def test_decision_mirror_shows_scope_citations_and_skips_listen_noise():
    from app.routers.meetings import meeting_decisions

    assert meeting_decisions("tool_call", {"name": "meeting_listen"}) == []
    assert (
        meeting_decisions("tool_result", {"name": "meeting_listen", "result": "{}"})
        == []
    )
    # the listen step logs scope decisions, the agent's own gate call is not repeated
    assert (
        meeting_decisions(
            "tool_result",
            {"name": "scope_gate", "result": json.dumps({"decision": "decline"})},
        )
        == []
    )

    rag = {
        "scope": "self",
        "query": "roadmap",
        "results": [
            {"text": "Q3 ships auth", "score": 0.81, "title": "Roadmap notes"},
            {"text": "Q4 ships billing", "score": 0.5, "source": "plan.md"},
        ],
    }
    [(kind, text, detail)] = meeting_decisions(
        "tool_result", {"name": "persona_rag", "result": json.dumps(rag)}
    )
    assert kind == "cite" and "2 sources" in text
    assert [c["title"] for c in detail["citations"]] == ["Roadmap notes", "plan.md"]

    denied = {"scope_denied": True, "requested_scope": "client:acme"}
    [(kind, text, _)] = meeting_decisions(
        "tool_result",
        {"name": "persona_rag", "result": json.dumps(denied), "is_error": True},
    )
    assert kind == "decline" and "client:acme" in text

    assert (
        meeting_decisions("tool_result", {"name": "meeting_speak", "result": "ok"})
        == []
    )
    [(kind, _, _)] = meeting_decisions(
        "tool_result", {"name": "meeting_speak", "result": "boom", "is_error": True}
    )
    assert kind == "error"
    assert (
        meeting_decisions(
            "tool_result",
            {
                "name": "meeting_listen",
                "result": "Kill-switch active — exiting.",
                "is_error": True,
            },
        )
        == []
    )


def test_snapshot_keeps_history_and_closes_a_live_meeting():
    from app.routers.meetings import apply_snapshot

    m = _meeting(status="live")
    apply_snapshot(m, [{"text": "hi"}], [{"kind": "join"}], "We covered the roadmap.")
    assert m.status == "done" and m.ended_at is not None
    assert m.notes["transcript"] == [{"text": "hi"}]
    assert m.transcript_count == 1 and m.decision_count == 1
    assert m.summary == "We covered the roadmap."
    # a killed meeting stays killed, an existing summary is kept
    k = _meeting(status="killed", summary="first")
    apply_snapshot(k, [], [], "second")
    assert k.status == "killed" and k.summary == "first"


@pytest.mark.asyncio
async def test_rehearsal_needs_a_topic_and_a_meeting_that_is_not_live():
    from app.routers import meetings

    for m, code in ((_meeting(scope_allow=[]), 400), (_meeting(status="live"), 409)):
        with patch.object(meetings, "_load", AsyncMock(return_value=m)):
            resp = await meetings.start_rehearsal(str(m.id), {}, user=_user(), db=None)
        assert resp.status_code == code


@pytest.mark.asyncio
async def test_rehearsal_runs_the_meeting_agent_under_its_own_key():
    from app.routers import meetings

    m = _meeting()
    fake = FakeRedis()
    with patch.object(meetings, "_load", AsyncMock(return_value=m)), patch.object(
        meetings, "_meeting_budget_error", AsyncMock(return_value=None)
    ), patch.object(meetings, "_redis", AsyncMock(return_value=fake)), patch.object(
        meetings, "_run_meeting_agent"
    ) as run, patch.object(
        meetings.asyncio, "create_task"
    ):
        resp = await meetings.start_rehearsal(str(m.id), {}, user=_user(), db=None)
        data = _body(resp)["data"]
        rid = data["rehearsal_id"]
        assert rid.startswith("rehearsal-") and data["status"] == "starting"
        # same agent runner as live, keyed apart from the real meeting
        assert run.call_args.kwargs == {"key": rid, "rehearsal": True}
        scope = fake.h[f"meeting:{rid}:scope"]
        assert scope["provider"] == "rehearsal"
        assert scope["allow"] == "roadmap" and scope["defer"] == "pricing"
        assert m.status == "authorized"

        # a second click resumes the running rehearsal
        resp = await meetings.start_rehearsal(str(m.id), {}, user=_user(), db=None)
        assert _body(resp)["data"]["rehearsal_id"] == rid

        resp = await meetings.rehearsal_turn(
            str(m.id), {"speaker": "Dana", "text": "Roadmap?"}, user=_user(), db=None
        )
        assert _body(resp)["data"]["queued"] is True
        [raw] = fake.l[f"meeting:{rid}:rehearsal:turns"]
        assert json.loads(raw)["speaker"] == "Dana"

        resp = await meetings.rehearsal_turn(
            str(m.id), {"text": "  "}, user=_user(), db=None
        )
        assert resp.status_code == 400

        resp = await meetings.end_rehearsal(str(m.id), user=_user(), db=None)
        assert _body(resp)["data"]["status"] == "ending"
        resp = await meetings.rehearsal_turn(
            str(m.id), {"text": "more?"}, user=_user(), db=None
        )
        assert resp.status_code == 409
