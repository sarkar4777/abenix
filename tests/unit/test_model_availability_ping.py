"""The availability probe must test the model a request will really run on."""

import asyncio
from types import SimpleNamespace

from app.services import model_availability as ma


class _Messages:
    def __init__(self, sent: list[str]) -> None:
        self.sent = sent

    async def create(self, *, model, max_tokens, messages):
        self.sent.append(model)
        if model != "claude-haiku-4-5":
            raise RuntimeError("Error code: 429 - rate_limit_error")
        return SimpleNamespace()


def _helper(used_sub: bool, sent: list[str]):
    client = SimpleNamespace(messages=_Messages(sent))
    return SimpleNamespace(
        build_async_client=lambda: (client, used_sub),
        effective_model=lambda m: "claude-haiku-4-5",
    )


def test_exclusive_subscription_probes_the_model_it_serves(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(ma, "_subscription_helper", lambda: _helper(True, sent))
    ok, err, _ = asyncio.run(ma._ping_anthropic("claude-sonnet-4-5-20250929"))
    assert ok and err is None
    assert sent == ["claude-haiku-4-5"]


def test_api_key_probes_the_named_model(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(ma, "_subscription_helper", lambda: _helper(False, sent))
    ok, err, _ = asyncio.run(ma._ping_anthropic("claude-sonnet-4-5-20250929"))
    assert not ok and "429" in err
    assert sent == ["claude-sonnet-4-5-20250929"]
