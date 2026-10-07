"""BPM Analyzer: subscription routing, honest fallbacks, privacy, upload labels and the PDF export."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

from app.routers import bpm_analyzer as bpm


def _cfg(usable=True, exclusive=True, default_model="claude-opus-5"):
    return SimpleNamespace(
        usable=usable, enabled=usable, exclusive=exclusive, default_model=default_model
    )


def _fake_sub(cfg, client=None):
    def effective_model(model):
        if not cfg.usable:
            return model
        if cfg.exclusive:
            return cfg.default_model
        return model

    return SimpleNamespace(
        get_config=lambda refresh=False: cfg,
        effective_model=effective_model,
        build_async_client=lambda api_key=None: (client, cfg.usable),
    )


TEXT_MSGS = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
AUDIO_MSGS = [
    {
        "role": "user",
        "content": [{"type": "audio", "source": {"type": "base64", "data": ""}}],
    }
]


# routing


def test_exclusive_subscription_takes_every_model(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg()))
    for model in ("gpt-4o", "gemini-2.5-pro", "claude-sonnet-4-5-20250929"):
        provider, m, note = asyncio.run(bpm._first_route(model, TEXT_MSGS))
        assert provider == bpm.SUBSCRIPTION
        assert m == "claude-opus-5"
        assert note is None


def test_non_exclusive_subscription_takes_only_claude(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg(exclusive=False)))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    assert asyncio.run(bpm._first_route("claude-haiku-4-5", TEXT_MSGS))[:2] == (
        bpm.SUBSCRIPTION,
        "claude-haiku-4-5",
    )
    assert asyncio.run(bpm._first_route("gpt-4o", TEXT_MSGS))[:2] == (
        "openai",
        "gpt-4o",
    )


def test_unusable_subscription_routes_natively(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg(usable=False)))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    assert (
        asyncio.run(bpm._first_route("claude-haiku-4-5", TEXT_MSGS))[0] == "anthropic"
    )


def test_missing_key_for_requested_model_uses_the_subscription_and_says_so(monkeypatch):
    sub = _fake_sub(_cfg(exclusive=False))
    sub.map_model = lambda model, cfg=None: "claude-opus-5"
    monkeypatch.setattr(bpm, "_subscription", lambda: sub)
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    provider, model, note = asyncio.run(bpm._first_route("gemini-2.5-pro", TEXT_MSGS))
    assert (provider, model) == (bpm.SUBSCRIPTION, "claude-opus-5")
    assert "No credential" in note


def test_missing_key_without_subscription_moves_to_a_configured_provider(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: None)
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    provider, model, note = asyncio.run(bpm._first_route("gemini-2.5-pro", TEXT_MSGS))
    assert (provider, model) == ("openai", "gpt-4o")
    assert "gpt-4o answered instead" in note


def test_audio_goes_to_gemini_and_says_why(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg()))
    provider, model, note = asyncio.run(bpm._first_route("claude-opus-5", AUDIO_MSGS))
    assert provider == "google"
    assert model.startswith("gemini")
    assert note and "Gemini" in note


def test_subscription_rate_limit_falls_back_and_is_reported(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg()))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    calls = []

    async def dispatch(
        *, system_prompt, messages, model, force_json=False, provider=None
    ):
        calls.append((provider, model))
        if provider == bpm.SUBSCRIPTION:
            raise RuntimeError("Error code: 429 rate_limit_error")
        return "report", {
            "model": "gpt-4o-2024-08-06",
            "input_tokens": 1,
            "output_tokens": 1,
            "cost": 0.01,
            "duration_ms": 5,
        }

    async def no_sleep(_):
        return None

    monkeypatch.setattr(bpm, "_dispatch_vision", dispatch)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    text, meta = asyncio.run(
        bpm._run_vision_model(
            system_prompt="", messages=TEXT_MSGS, model="claude-sonnet-5"
        )
    )
    assert text == "report"
    # three tries on the subscription, then one on the fallback
    assert [c[0] for c in calls] == [bpm.SUBSCRIPTION] * 3 + ["openai"]
    assert meta["requested_model"] == "claude-sonnet-5"
    assert meta["provider"] == "openai"
    assert meta["fallback_from"] == bpm.SUBSCRIPTION
    assert meta["fallback_reason"] == "rate limited"
    rec = bpm._route_record(meta)
    assert rec["served_model"] == "gpt-4o-2024-08-06"
    assert rec["fallback_from"] == bpm.SUBSCRIPTION


def test_non_outage_error_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg()))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")

    async def dispatch(**kw):
        raise ValueError("bad request: image too large")

    monkeypatch.setattr(bpm, "_dispatch_vision", dispatch)
    with pytest.raises(ValueError):
        asyncio.run(
            bpm._run_vision_model(system_prompt="", messages=TEXT_MSGS, model="gpt-4o")
        )


def test_subscription_only_install_runs_anthropic_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _Messages:
        async def create(self, **kw):
            self.kw = kw
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="ok")],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                model=kw["model"],
            )

    client = SimpleNamespace(messages=_Messages())
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg(), client))
    text, meta = asyncio.run(
        bpm._run_anthropic(
            system_prompt="s",
            messages=TEXT_MSGS,
            model="claude-opus-5",
            use_subscription=True,
        )
    )
    assert text == "ok"
    assert meta["cost"] == 0.0
    assert client.messages.kw["model"] == "claude-opus-5"


def test_api_key_path_still_requires_the_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        asyncio.run(
            bpm._run_anthropic(
                system_prompt="", messages=TEXT_MSGS, model="claude-opus-5"
            )
        )


def test_next_provider_tries_the_native_key_after_the_subscription(monkeypatch):
    monkeypatch.setattr(bpm, "_subscription", lambda: _fake_sub(_cfg()))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    assert bpm._next_provider_model([bpm.SUBSCRIPTION], "claude-sonnet-5") == (
        "anthropic",
        "claude-sonnet-5",
    )


# upload labels and notices


def _pdf_atts(n, total):
    return [
        {
            "type": "pdf_page",
            "page": i + 1,
            "filename": "flow.pdf",
            "total_pages": total,
        }
        for i in range(n)
    ]


def test_upload_label_and_truncation_notice_for_pdf():
    assert bpm._upload_label(_pdf_atts(3, 3)) == "Uploaded flow.pdf (3 pages)"
    assert (
        bpm._upload_label(_pdf_atts(20, 57))
        == "Uploaded flow.pdf (first 20 of 57 pages)"
    )
    assert bpm._upload_notices(_pdf_atts(3, 3)) == []
    notes = bpm._upload_notices(_pdf_atts(20, 57))
    assert notes and "57 pages" in notes[0] and "first 20" in notes[0]


def test_text_truncation_is_recorded_and_reported():
    att = bpm._text_attachment("x" * (bpm.MAX_TEXT_CHARS + 10), "sop.txt", "txt")
    assert att["truncated"] is True
    assert len(att["text"]) == bpm.MAX_TEXT_CHARS
    assert "200,000" in bpm._upload_notices([att])[0]
    assert "of 200,010 characters" in bpm._upload_label([att])


def test_unreadable_pdf_maps_to_plain_language():
    with pytest.raises(bpm.UploadError) as exc:
        bpm._process_upload(b"%PDF-1.4 not really", "application/pdf", "x.pdf")
    assert str(exc.value) == bpm._UNREADABLE_PDF
    assert (
        bpm._friendly_upload_error(RuntimeError("Failed to open stream"))
        == bpm._UNREADABLE_PDF
    )


def test_unsupported_type_is_plain_language():
    with pytest.raises(bpm.UploadError, match="not supported"):
        bpm._process_upload(b"abc", "application/zip", "a.zip")


def _msg(role, content, attachments=None, at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        role=role,
        content=content,
        attachments=attachments,
        model_used=None,
        input_tokens=0,
        output_tokens=0,
        cost=0,
        duration_ms=None,
        created_at=at or datetime.now(timezone.utc),
    )


def test_user_bubble_shows_label_and_model_gets_instruction():
    atts = _pdf_atts(2, 2)
    first = _msg("user", "Uploaded flow.pdf (2 pages)", atts)
    assert bpm._serialize_message(first)["content"] == "Uploaded flow.pdf (2 pages)"
    # older threads stored the instruction as content, the bubble still shows the label
    legacy = _msg("user", bpm._opening_for("pdf_page"), atts)
    assert bpm._serialize_message(legacy)["content"] == "Uploaded flow.pdf (2 pages)"

    history = [
        first,
        _msg("assistant", "report"),
        _msg("user", "q1"),
        _msg("assistant", "[error] boom"),
    ]
    msgs = bpm._build_anthropic_messages(
        atts, history_turns=history, new_user_question="q2"
    )
    first_texts = [b["text"] for b in msgs[0]["content"] if b["type"] == "text"]
    assert first_texts[-1] == bpm._opening_for("pdf_page")
    # the error turn is dropped and the two user turns merge
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == "q1\n\nq2"


def test_upload_turn_has_no_trailing_empty_message():
    atts = _pdf_atts(1, 1)
    msgs = bpm._build_anthropic_messages(
        atts, history_turns=[_msg("user", "Uploaded", atts)], new_user_question=""
    )
    assert len(msgs) == 1


def test_assistant_message_carries_its_route():
    m = _msg(
        "assistant",
        "report",
        [
            bpm._route_record(
                {
                    "provider": "openai",
                    "fallback_from": bpm.SUBSCRIPTION,
                    "model": "gpt-4o",
                }
            )
        ],
    )
    route = bpm._serialize_message(m)["route"]
    assert route["provider"] == "openai"
    assert route["fallback_from"] == bpm.SUBSCRIPTION


# thread state


def test_thread_state():
    now = datetime.now(timezone.utc)
    assert bpm._thread_state(None, None, None) == "empty"
    assert (
        bpm._thread_state("user", "x", now - timedelta(seconds=30), now) == "analyzing"
    )
    assert bpm._thread_state("user", "x", now - timedelta(hours=2), now) == "stalled"
    assert bpm._thread_state("assistant", "[error] x", now, now) == "failed"
    assert bpm._thread_state("assistant", "# Report", now, now) == "ready"
    # naive timestamps from some drivers still compare
    assert (
        bpm._thread_state(
            "user", "x", (now - timedelta(seconds=5)).replace(tzinfo=None), now
        )
        == "analyzing"
    )


# privacy


class _CaptureDB:
    def __init__(self, row=None):
        self.row = row
        self.stmts = []

    async def execute(self, stmt):
        self.stmts.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: self.row)


def test_owned_thread_filters_by_owner_and_app():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    db = _CaptureDB(row=None)
    conv, err = asyncio.run(bpm._owned_thread(db, str(uuid.uuid4()), user))
    assert conv is None and err.status_code == 404
    sql = str(db.stmts[0].compile(compile_kwargs={"literal_binds": False}))
    assert "conversations.user_id" in sql
    assert "conversations.tenant_id" in sql
    assert "conversations.app_slug" in sql


def test_owned_thread_rejects_bad_ids():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    conv, err = asyncio.run(bpm._owned_thread(_CaptureDB(), "nope", user))
    assert conv is None and err.status_code == 400


def test_list_threads_is_owner_scoped(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())

    class _DB:
        def __init__(self):
            self.stmts = []

        async def execute(self, stmt):
            self.stmts.append(stmt)
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: []), all=lambda: []
            )

    db = _DB()
    resp = asyncio.run(bpm.list_threads(SimpleNamespace(), 50, user, db))
    assert json.loads(resp.body)["data"] == {"threads": []}
    assert "conversations.user_id" in str(db.stmts[0])


# smoke test runs in process


def test_smoke_test_runs_through_the_execute_route(monkeypatch):
    from app.routers import agents as agents_router

    seen = {}

    async def fake_execute(agent_id, body, request, user, db):
        seen.update(agent_id=agent_id, wait=body.wait, stream=body.stream, user=user)
        return JSONResponse(
            {
                "data": {
                    "execution_id": "e1",
                    "output": "done",
                    "model": "claude-opus-5",
                    "cost": 0.0,
                    "duration_ms": 12,
                    "tool_calls": [],
                },
                "error": None,
            }
        )

    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)
    user = SimpleNamespace(id=uuid.uuid4())
    out = asyncio.run(bpm._smoke_test(SimpleNamespace(), user, object(), "a1", "hello"))
    assert out["ok"] is True and out["output"] == "done" and out["execution_id"] == "e1"
    assert seen == {"agent_id": "a1", "wait": True, "stream": False, "user": user}


def test_smoke_test_reports_a_failed_execution(monkeypatch):
    from app.routers import agents as agents_router

    async def fake_execute(*a, **kw):
        return JSONResponse(
            {
                "data": {"status": "failed", "error": "tool missing", "output": ""},
                "error": None,
            }
        )

    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)
    out = asyncio.run(
        bpm._smoke_test(SimpleNamespace(), SimpleNamespace(), object(), "a1", "x")
    )
    assert out["ok"] is False and out["error"] == "tool missing"


def test_smoke_test_reports_an_error_envelope(monkeypatch):
    from app.routers import agents as agents_router

    async def fake_execute(*a, **kw):
        return JSONResponse(
            {"data": None, "error": {"message": "Agent not found"}}, status_code=404
        )

    monkeypatch.setattr(agents_router, "execute_agent", fake_execute)
    out = asyncio.run(
        bpm._smoke_test(SimpleNamespace(), SimpleNamespace(), object(), "a1", "x")
    )
    assert out == {"ok": False, "error": "Agent not found"}


# PDF export markdown


def test_code_spans_keep_their_underscores():
    html = bpm._md_to_html("Call `send_email_now` then _review_ the `a_b_c` flag")
    assert "<code>send_email_now</code>" in html
    assert "<code>a_b_c</code>" in html
    assert "<i>review</i>" in html


def test_snake_case_outside_code_is_left_alone():
    assert "<i>" not in bpm._md_to_html("use the field risk_score_v2 here")


def test_blank_table_header_is_dropped():
    html = bpm._md_to_html("| | |\n|---|---|\n| a | b |")
    assert "<th>" not in html
    assert "<td>a</td>" in html
    assert "<th>Step</th>" in bpm._md_to_html("| Step | Owner |\n|---|---|\n| a | b |")


def test_plain_preview_strips_markdown():
    out = bpm._plain_preview(
        "# Detailed Report\n\n**Bold** and `code_x` | cell |\n- item"
    )
    assert out == "Detailed Report Bold and code_x cell item"
