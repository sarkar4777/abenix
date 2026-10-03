"""Event matching, templating, backoff and target safety."""

from __future__ import annotations

import asyncio

from app.services import events as E


def test_matches_globs_and_filters():
    sub = {
        "events": ["decision.*"],
        "filter": {"decision_key": ["a", "b"], "risk": "high"},
    }
    assert E.matches(sub, "decision.published", {"decision_key": "a", "risk": "high"})
    assert not E.matches(
        sub, "decision.published", {"decision_key": "c", "risk": "high"}
    )
    assert not E.matches(sub, "execution.failed", {"decision_key": "a", "risk": "high"})
    assert E.matches({"events": ["*"]}, "anything.here", {})
    assert E.matches(
        {"events": ["execution.failed"], "filter": {"agent.id": "x"}},
        "execution.failed",
        {"agent": {"id": "x"}},
    )


def test_render_fills_placeholders():
    env = {
        "type": "decision.published",
        "data": {"decision_key": "k", "version": 4, "closed": [3]},
    }
    out = E.render(
        "Reassess {{data.decision_key}} v{{data.version}} after {{type}}, closed {{data.closed}} {{missing}}",
        env,
    )
    assert out == "Reassess k v4 after decision.published, closed [3] "


def test_backoff_grows_and_caps():
    assert E.backoff(1).total_seconds() == 10
    assert E.backoff(4).total_seconds() == 80
    assert E.backoff(30).total_seconds() == 3600


def test_signature_is_hmac_sha256():
    import hashlib
    import hmac

    assert E.sign("s", "body") == hmac.new(b"s", b"body", hashlib.sha256).hexdigest()


def test_private_targets_are_refused(monkeypatch):
    monkeypatch.delenv("EVENTS_ALLOW_PRIVATE_TARGETS", raising=False)
    assert "private" in asyncio.run(E.unsafe_target("http://127.0.0.1:9/x"))
    assert "not http" in asyncio.run(E.unsafe_target("ftp://example.com"))
    monkeypatch.setenv("EVENTS_ALLOW_PRIVATE_TARGETS", "1")
    assert asyncio.run(E.unsafe_target("http://127.0.0.1:9/x")) is None


def test_catalog_validation_accepts_globs_and_legacy():
    from app.routers.webhook_config import _bad_events

    assert _bad_events(["decision.*", "execution.failed", "*", "agent.published"]) == []
    assert _bad_events(["nope.thing", ""]) == ["nope.thing", ""]
