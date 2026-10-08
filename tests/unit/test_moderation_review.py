"""Hold for review: the gate, masking, the review service and retention."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from engine.moderation_client import (
    ACTION_BLOCK,
    ACTION_HOLD,
    content_hash,
    evaluate,
    locate_provider_spans,
    mask_spans,
    merge_spans,
    pattern_spans,
)
from engine.moderation_gate import GateConfig, ModerationBlocked, ModerationHeld, check
from engine.moderation_hold import RELEASED_STATUSES, priority_for, seal, unseal
from models.moderation_policy import ModerationReview

TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _provider(scores: dict, per_input: list[dict] | None = None):
    async def fake(content, model="omni-moderation-latest"):
        if isinstance(content, list):
            rows = per_input or []
            return {
                "results": [
                    {
                        "categories": {k: v >= 0.5 for k, v in r.items()},
                        "category_scores": r,
                    }
                    for r in rows
                ]
            }
        return {
            "results": [
                {
                    "flagged": any(v >= 0.5 for v in scores.values()),
                    "categories": {k: v >= 0.5 for k, v in scores.items()},
                    "category_scores": scores,
                }
            ]
        }

    return fake


async def _no_provider(_c, model="x"):
    raise RuntimeError("OPENAI_API_KEY not configured")


# ── spans and masking ────────────────────────────────────────────


def test_pattern_spans_are_labelled_by_the_policy_pattern_index():
    spans = pattern_spans("call 555-12-3456 now", [r"\bnope\b", r"\d{3}-\d{2}-\d{4}"])
    assert spans == [{"start": 5, "end": 16, "category": "custom:1"}]


def test_merge_joins_overlaps_and_keeps_categories():
    out = merge_spans(
        [
            {"start": 5, "end": 9, "category": "custom:0"},
            {"start": 0, "end": 6, "category": "hate"},
            {"start": 20, "end": 22, "category": "custom:1"},
        ]
    )
    assert out == [
        {"start": 0, "end": 9, "category": "hate,custom:0"},
        {"start": 20, "end": 22, "category": "custom:1"},
    ]


def test_mask_spans_replaces_each_span_once():
    text = "my code is AB12 and AB12"
    spans = pattern_spans(text, [r"AB\d\d"])
    assert mask_spans(text, spans, "#") == "my code is # and #"
    assert mask_spans(text, [], "#") == text


@pytest.mark.asyncio
async def test_provider_categories_mask_the_whole_text_unless_localised():
    whole = await locate_provider_spans(
        "a. b.",
        ["hate"],
        thresholds={},
        default_threshold=0.5,
        model="m",
        localize=False,
    )
    assert whole == [{"start": 0, "end": 5, "category": "hate"}]


@pytest.mark.asyncio
async def test_a_hold_asks_the_provider_per_sentence_to_find_the_span():
    text = "Hello there. You are awful. Bye."
    with patch(
        "engine.moderation_client._call_openai",
        new=_provider({}, per_input=[{"hate": 0.0}, {"hate": 0.9}, {"hate": 0.1}]),
    ):
        spans = await locate_provider_spans(
            text,
            ["hate"],
            thresholds={},
            default_threshold=0.5,
            model="m",
            localize=True,
        )
    assert len(spans) == 1
    assert text[spans[0]["start"] : spans[0]["end"]].strip() == "You are awful."


@pytest.mark.asyncio
async def test_span_lookup_falls_back_to_the_whole_text_when_the_answer_is_short():
    text = "One. Two. Three."
    with patch(
        "engine.moderation_client._call_openai",
        new=_provider({}, per_input=[{"hate": 0.9}]),
    ):
        spans = await locate_provider_spans(
            text,
            ["hate"],
            thresholds={},
            default_threshold=0.5,
            model="m",
            localize=True,
        )
    assert spans == [{"start": 0, "end": len(text), "category": "hate"}]


# ── evaluate and the gate ────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_hold_is_held_with_pattern_spans():
    with patch("engine.moderation_client._call_openai", new=_no_provider):
        d = await evaluate(
            "the vault code is ZX-99",
            custom_patterns=[r"ZX-\d+"],
            default_action=ACTION_HOLD,
        )
    assert d.action == ACTION_HOLD
    assert d.outcome == "held"
    assert d.triggered_categories == ["custom:0"]
    assert d.spans == [{"start": 18, "end": 23, "category": "custom:0"}]


@pytest.mark.asyncio
async def test_block_outranks_hold():
    with patch(
        "engine.moderation_client._call_openai", new=_provider({"violence": 0.95})
    ):
        d = await evaluate(
            "ZX-1 and violence",
            custom_patterns=[r"ZX-\d"],
            default_action=ACTION_HOLD,
            category_actions={"violence": ACTION_BLOCK},
        )
    assert d.action == ACTION_BLOCK


@pytest.mark.asyncio
async def test_gate_hold_raises_a_held_block_with_the_full_text_for_the_sink():
    seen: dict = {}
    cfg = GateConfig(
        default_action=ACTION_HOLD,
        custom_patterns=[r"ZX-\d+"],
        redaction_mask="##",
        hold_timeout_minutes=15,
        hold_timeout_action="release",
        conversation_id="c1",
        event_sink=lambda **kw: seen.update(kw),
    )
    with patch("engine.moderation_client._call_openai", new=_no_provider):
        with pytest.raises(ModerationHeld) as exc:
            await check("use ZX-42 please", source="pre_llm", config=cfg)
    held = exc.value
    # code that only knows blocks still refuses it
    assert isinstance(held, ModerationBlocked)
    assert held.timeout_minutes == 15 and held.timeout_action == "release"
    assert seen["content_preview"] == "use ## please"
    hold = seen["hold"]
    assert hold["review_id"] == held.review_id
    assert hold["content"] == "use ZX-42 please"
    assert hold["conversation_id"] == "c1"
    assert hold["spans"][0]["category"] == "custom:0"


@pytest.mark.asyncio
async def test_provider_hits_are_masked_in_the_event_preview():
    seen: dict = {}
    cfg = GateConfig(
        default_action=ACTION_BLOCK, event_sink=lambda **kw: seen.update(kw)
    )
    with patch("engine.moderation_client._call_openai", new=_provider({"hate": 0.97})):
        with pytest.raises(ModerationBlocked):
            await check("something hateful", source="pre_llm", config=cfg)
    assert "hateful" not in seen["content_preview"]


@pytest.mark.asyncio
async def test_a_released_message_goes_through_once():
    seen: list = []
    text = "use ZX-42 please"
    cfg = GateConfig(
        default_action=ACTION_HOLD,
        custom_patterns=[r"ZX-\d+"],
        released={content_hash(text): "rev-1"},
        event_sink=lambda **kw: seen.append(kw),
    )
    with patch("engine.moderation_client._call_openai", new=_no_provider):
        out, d = await check(text, source="pre_llm", config=cfg)
        assert out == text and d.outcome == "allowed"
        assert seen[-1]["consumed_review_id"] == "rev-1"
        # the second send is moderated again
        with pytest.raises(ModerationHeld):
            await check(text, source="pre_llm", config=cfg)


@pytest.mark.asyncio
async def test_a_release_never_skips_the_check_on_the_reply():
    text = "ZX-1"
    cfg = GateConfig(
        default_action=ACTION_HOLD,
        custom_patterns=[r"ZX-\d"],
        released={content_hash(text): "rev-1"},
    )
    with patch("engine.moderation_client._call_openai", new=_no_provider):
        with pytest.raises(ModerationHeld):
            await check(text, source="post_llm", config=cfg)


def test_held_text_explains_what_happens_next():
    from engine.agent_executor import _held, _moderation_block_text
    from engine.moderation_client import ModerationDecision

    mh = ModerationHeld(
        ModerationDecision(outcome="held", action=ACTION_HOLD),
        source="post_llm",
        content_preview="",
        review_id="r1",
        timeout_minutes=30,
        timeout_action="reject",
    )
    text = _moderation_block_text(mh, "Response")
    assert "The reply is waiting for review" in text and "30 minutes" in text
    assert _held(mh) == {"moderation_held": True, "moderation_review_id": "r1"}
    assert _held(ModerationBlocked(ModerationDecision(), "pre_llm", "")) == {}


# ── persistence helpers ──────────────────────────────────────────


def test_priority_follows_severity():
    assert priority_for(["sexual/minors"], {"sexual/minors": 0.2}) == 3
    assert priority_for(["hate"], {"hate": 0.9}) == 3
    assert priority_for(["custom:0"], {}) == 2
    assert priority_for(["hate"], {"hate": 0.55}) == 1


def test_held_text_is_encrypted_when_a_key_is_set(monkeypatch):
    monkeypatch.setenv(
        "ABENIX_DATA_KEY_KEK_BASE64", base64.b64encode(b"k" * 32).decode("ascii")
    )
    sealed = seal(TENANT, "secret words")
    assert sealed and sealed.startswith("v1:") and "secret" not in sealed
    assert unseal(TENANT, sealed) == "secret words"


def test_held_text_is_dropped_when_a_key_is_set_but_crypto_is_missing(monkeypatch):
    import builtins

    monkeypatch.setenv(
        "ABENIX_DATA_KEY_KEK_BASE64", base64.b64encode(b"k" * 32).decode("ascii")
    )
    real = builtins.__import__

    def no_crypto(name, *a, **k):
        if name == "app.core.crypto":
            raise ImportError("not in this image")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_crypto)
    assert seal(TENANT, "secret words") is None


@pytest.mark.asyncio
async def test_record_hold_keeps_masked_text_and_a_deadline():
    from engine.moderation_hold import record_hold

    added: list = []
    db = SimpleNamespace(add=added.append)
    review = await record_hold(
        db,
        tenant_id=TENANT,
        user_id=USER,
        policy_id=None,
        event_id=None,
        execution_id=None,
        source="pre_llm",
        categories=["custom:0"],
        scores={},
        hold={
            "review_id": str(uuid.uuid4()),
            "content": "code ZX-9 here",
            "spans": [{"start": 5, "end": 9, "category": "custom:0"}],
            "timeout_minutes": 45,
            "timeout_action": "release",
        },
        redaction_mask="##",
    )
    assert added == [review]
    assert review.masked_content == "code ## here"
    assert review.priority == 2 and review.status == "pending"
    assert review.timeout_action == "release"
    left = review.expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=44) < left <= timedelta(minutes=45)
    assert review.content_length == len("code ZX-9 here")


# ── retention settings ───────────────────────────────────────────


def test_retention_defaults_and_validation():
    from app.services.moderation_review import retention_from, validate_retention

    d = retention_from({})
    assert (
        d["held_content_days"],
        d["decision_record_days"],
        d["event_preview_days"],
    ) == (
        30,
        365,
        30,
    )
    ok, errs = validate_retention({"held_content_days": 0, "event_preview_days": 7})
    assert ok == {"held_content_days": 0, "event_preview_days": 7} and not errs
    _, errs = validate_retention({"held_content_days": 2.5})
    assert "whole number" in errs["held_content_days"]
    _, errs = validate_retention({"decision_record_days": 10})
    assert "between 30 and 3650" in errs["decision_record_days"]
    _, errs = validate_retention({"event_preview_days": True})
    assert errs["event_preview_days"]
    _, errs = validate_retention({"held_content_days": 90, "decision_record_days": 60})
    assert "longer than the decision record" in errs["held_content_days"]


def test_purge_statements_follow_each_tenants_settings_in_batches():
    from app.services import moderation_review as mr

    for sql, key in (
        (mr._PURGE_HELD, "held_content_days"),
        (mr._DROP_RECORDS, "decision_record_days"),
        (mr._EXPIRE_PREVIEWS, "event_preview_days"),
    ):
        s = str(sql)
        assert f"'moderation_retention'->>'{key}'" in s
        assert "LIMIT :batch" in s
    assert "status <> 'pending'" in str(mr._PURGE_HELD)
    assert "status <> 'pending'" in str(mr._DROP_RECORDS)


@pytest.mark.asyncio
async def test_purge_loops_until_a_short_batch():
    from app.services import moderation_review as mr

    counts = iter([5, 2, 0, 1])
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=lambda *a, **k: SimpleNamespace(rowcount=next(counts))
        ),
        commit=AsyncMock(),
    )
    out = await mr.purge_retention(db, batch=5)
    assert out == {"held_text": 7, "records": 0, "previews": 1}


# ── decisions ────────────────────────────────────────────────────


def _review(**kw) -> ModerationReview:
    base = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        user_id=USER,
        source="pre_llm",
        status="pending",
        priority=2,
        categories=["custom:0"],
        held_content="call ZX-9 now",
        content_length=13,
        masked_content="call ## now",
        redaction_mask="##",
        timeout_action="reject",
        history=[],
    )
    base.update(kw)
    return ModerationReview(**base)


@pytest.fixture
def quiet(monkeypatch):
    from app.services import moderation_review as mr

    monkeypatch.setattr(mr, "_tenant_settings", AsyncMock(return_value={}))
    monkeypatch.setattr(mr, "_deliver", AsyncMock())
    monkeypatch.setattr(mr, "_audit", AsyncMock())
    monkeypatch.setattr(mr, "_people", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.events.emit", AsyncMock())
    return mr


@pytest.mark.asyncio
async def test_reject_needs_a_reason(quiet):
    r = _review()
    with pytest.raises(quiet.ReviewError) as exc:
        await quiet.decide(None, r, actor=USER, action="reject", reason="  ")
    assert exc.value.error_code == "REASON_REQUIRED"
    assert r.status == "pending"


@pytest.mark.asyncio
async def test_redact_releases_the_edited_text(quiet):
    r = _review()
    await quiet.decide(None, r, actor=USER, action="redact", content="call ## now")
    assert r.status == "redacted" and r.decided_by == USER
    assert unseal(TENANT, r.released_content) == "call ## now"
    assert r.history[-1]["action"] == "redacted"
    quiet._deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_empty_redaction_is_refused(quiet):
    with pytest.raises(quiet.ReviewError) as exc:
        await quiet.decide(None, _review(), actor=USER, action="redact", content=" ")
    assert exc.value.error_code == "REDACTION_EMPTY"


@pytest.mark.asyncio
async def test_release_needs_the_full_text(quiet):
    r = _review(held_content=None)
    with pytest.raises(quiet.ReviewError) as exc:
        await quiet.decide(None, r, actor=USER, action="release")
    assert exc.value.error_code == "CONTENT_GONE"


@pytest.mark.asyncio
async def test_the_timeout_decides_without_a_person(quiet):
    r = _review(timeout_action="release")
    await quiet.decide(None, r, actor=None, action="release")
    assert r.status == "auto_released" and r.decided_by is None
    assert "automatically" in r.decision_reason
    r2 = _review()
    await quiet.decide(None, r2, actor=None, action="reject")
    assert r2.status == "auto_rejected"


@pytest.mark.asyncio
async def test_a_decided_item_cannot_be_decided_again(quiet):
    r = _review(status="rejected")
    with pytest.raises(quiet.ReviewError) as exc:
        await quiet.decide(None, r, actor=USER, action="release")
    assert exc.value.code == 409


@pytest.mark.asyncio
async def test_zero_day_retention_drops_the_full_text_at_decision(quiet, monkeypatch):
    monkeypatch.setattr(
        quiet,
        "_tenant_settings",
        AsyncMock(return_value={"moderation_retention": {"held_content_days": 0}}),
    )
    r = _review(source="post_llm")
    await quiet.decide(None, r, actor=USER, action="release")
    assert r.held_content is None and r.released_content is None
    assert r.content_purged_at is not None


@pytest.mark.asyncio
async def test_someone_elses_claim_blocks_a_member_but_not_an_admin(quiet):
    other = uuid.uuid4()
    r = _review(assigned_to=other)
    with pytest.raises(quiet.ReviewError) as exc:
        await quiet.claim(None, r, USER)
    assert exc.value.error_code == "REVIEW_CLAIMED"
    with pytest.raises(quiet.ReviewError):
        await quiet.decide(None, r, actor=USER, action="release")
    await quiet.claim(None, r, USER, is_admin=True)
    assert r.assigned_to == USER


@pytest.mark.asyncio
async def test_only_the_claimer_or_an_admin_unassigns(quiet):
    r = _review(assigned_to=uuid.uuid4())
    with pytest.raises(quiet.ReviewError):
        await quiet.unassign(None, r, USER, is_admin=False)
    await quiet.unassign(None, r, USER, is_admin=True)
    assert r.assigned_to is None


def test_the_author_sees_their_words_while_waiting_and_the_outcome_after():
    from app.services.moderation_review import owner_view

    pending = owner_view(_review())
    assert pending["status"] == "pending" and pending["content"] == "call ZX-9 now"
    rejected = owner_view(_review(status="rejected", decision_reason="Account number"))
    assert rejected["content"] is None and rejected["reason"] == "Account number"
    released = owner_view(
        _review(status="redacted", released_content=seal(TENANT, "call ## now"))
    )
    assert released["content"] == "call ## now" and released["reason"] is None
    assert "redacted" in RELEASED_STATUSES


def test_serialized_rows_never_carry_the_full_text():
    from app.services.moderation_review import serialize

    row = serialize(_review(), {}, {}, me=USER)
    assert "content" not in row and row["preview"] == "call ## now"
    full = serialize(_review(), {}, {}, me=USER, full=True)
    assert full["content"] == "call ZX-9 now"


# ── wiring ───────────────────────────────────────────────────────


def test_review_capability_and_notification_preference_exist():
    from app.core.capabilities import KEYS, ROLE_DEFAULTS, holds
    from app.core.notifications import pref_key_for

    assert "moderation.review" in KEYS
    assert holds(ROLE_DEFAULTS["admin"], "moderation.review")
    assert not holds(ROLE_DEFAULTS["user"], "moderation.review")
    assert pref_key_for("moderation_review_requested") == "moderation_reviews"


def test_events_catalogue_lists_hold_events():
    from app.services.events import CATALOG

    assert {"moderation.held", "moderation.decided"} <= set(CATALOG)


def test_gdpr_erase_covers_held_content_and_previews():
    from app.services import gdpr_purge

    assert "moderation_reviews" in str(gdpr_purge._ERASE_HELD)
    assert "held_content = NULL" in str(gdpr_purge._ERASE_HELD)
    assert "status = 'pending'" in str(gdpr_purge._CLOSE_HELD)
    assert "content_preview = NULL" in str(gdpr_purge._ERASE_EVENT_PREVIEWS)


@pytest.mark.asyncio
async def test_gdpr_erase_runs_the_moderation_statements():
    from app.services import gdpr_purge

    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    subject = gdpr_purge.Subject(tenant_id=TENANT, user_id=USER)
    n = await gdpr_purge._erase_authored_content(db, subject)
    sql = [str(c.args[0]) for c in db.execute.call_args_list]
    assert n == 6
    assert any("moderation_events" in s for s in sql)
    assert any("UPDATE moderation_reviews SET held_content" in s for s in sql)


def test_scheduler_registers_the_review_and_retention_jobs(monkeypatch):
    from app.core import scheduler

    added: list = []

    class Fake:
        running = False

        def add_job(self, fn, **kw):
            added.append(kw["id"])

        def start(self):
            pass

    monkeypatch.setattr(scheduler, "get_scheduler", lambda: Fake())
    scheduler.start_scheduler()
    assert "moderation_review_tick" in added and "moderation_retention" in added
