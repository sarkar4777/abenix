"""A model connection change re-checks availability soon, once, not at the next hourly run."""

from __future__ import annotations

import asyncio

from app.services import model_availability as ma


def test_reprobe_runs_once_for_a_burst_of_changes(monkeypatch):
    calls = []

    async def fake_pings():
        calls.append(1)
        return {}

    monkeypatch.setattr(ma, "run_pings", fake_pings)
    monkeypatch.setattr(ma, "_reprobe_task", None)

    async def scenario():
        for _ in range(5):
            ma.schedule_reprobe(delay=0.01)
        await asyncio.sleep(0.1)

    asyncio.run(scenario())
    assert calls == [1]


def test_reprobe_outside_a_loop_is_a_no_op(monkeypatch):
    monkeypatch.setattr(ma, "_reprobe_task", None)
    ma.schedule_reprobe()
    assert ma._reprobe_task is None


def test_provider_keys_cover_the_llm_providers():
    assert {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"} <= set(
        ma.PROVIDER_KEYS
    )
