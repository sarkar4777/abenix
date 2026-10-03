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
