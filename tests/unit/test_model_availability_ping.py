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


def _plan_helper(usable: bool):
    return SimpleNamespace(get_config=lambda: SimpleNamespace(usable=usable))


def _clear_google_keys(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_keyless_gemini_on_a_subscription_is_not_marked_down(monkeypatch):
    _clear_google_keys(monkeypatch)
    monkeypatch.setattr(ma, "_subscription_helper", lambda: _plan_helper(True))
    out = asyncio.run(ma.ping_one("gemini-2.0-flash", "google"))
    assert out["ok"] is True and out["error"] is None


def test_keyless_gemini_without_a_subscription_still_fails_its_probe(monkeypatch):
    _clear_google_keys(monkeypatch)
    monkeypatch.setattr(ma, "_subscription_helper", lambda: _plan_helper(False))

    async def down(model):
        return False, "no key", None

    monkeypatch.setitem(ma._PINGER, "google", down)
    assert asyncio.run(ma.ping_one("gemini-2.0-flash", "google"))["ok"] is False
