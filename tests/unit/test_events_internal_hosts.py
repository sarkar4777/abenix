"""Outbound webhooks reach a named in-cluster receiver and nothing else private."""

from __future__ import annotations

import asyncio

from app.services.events import unsafe_target


def test_private_targets_blocked_unless_named(monkeypatch) -> None:
    monkeypatch.delenv("EVENTS_ALLOW_PRIVATE_TARGETS", raising=False)
    monkeypatch.setenv("EVENTS_ALLOWED_INTERNAL_HOSTS", "receiver.internal , other.svc")
    assert asyncio.run(unsafe_target("http://localhost:8080/x"))
    assert asyncio.run(unsafe_target("http://receiver.internal:8008/hook")) is None
    assert asyncio.run(unsafe_target("http://other.svc/hook")) is None
    # a lookalike suffix is not the named host
    assert asyncio.run(unsafe_target("http://evil.receiver.internal/hook"))


def test_named_internal_receiver_can_be_saved(monkeypatch) -> None:
    from app.routers.webhook_config import _validate_url

    monkeypatch.setenv("EVENTS_ALLOWED_INTERNAL_HOSTS", "receiver.ns.svc.cluster.local")
    assert _validate_url("http://receiver.ns.svc.cluster.local:8008/hook") is None
    assert _validate_url("http://other.ns.svc.cluster.local/hook")
    assert _validate_url("http://localhost/hook")
