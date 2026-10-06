"""An agent run is refused up front, with a plain message, when no model provider has a key."""

import asyncio
import json
from types import SimpleNamespace


def _run(providers, agent):
    import app.routers.llm_models as lm
    from app.core.model_gate import model_unavailable_error

    async def fake_probe(db):
        if isinstance(providers, Exception):
            raise providers
        return providers

    real = lm._probe_providers
    lm._probe_providers = fake_probe
    try:
        return asyncio.run(model_unavailable_error(None, agent))
    finally:
        lm._probe_providers = real


AGENT = SimpleNamespace(model_config_={"model": "claude-sonnet-4-5"}, mode="agent")
NONE = {p: {"configured": False, "reason": "not set"} for p in ("anthropic", "openai", "google", "azure", "claude_subscription")}


def test_no_provider_refuses_with_a_plain_message():
    res = _run(NONE, AGENT)
    assert res is not None and res.status_code == 503
    body = json.loads(res.body)
    assert body["error"]["code"] == "NO_MODEL_CONFIGURED" or "NO_MODEL_CONFIGURED" in json.dumps(body)
    assert "Tool Configuration" in json.dumps(body)


def test_any_configured_provider_lets_the_run_start():
    some = {**NONE, "google": {"configured": True, "reason": None}}
    assert _run(some, AGENT) is None


def test_pipelines_are_not_refused():
    pipe = SimpleNamespace(model_config_={"pipeline_config": {"nodes": []}}, mode="pipeline")
    assert _run(NONE, pipe) is None


def test_a_broken_check_never_blocks_a_run():
    assert _run(RuntimeError("db down"), AGENT) is None
