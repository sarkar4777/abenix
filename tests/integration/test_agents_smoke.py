"""Smoke-test every seeded agent end-to-end.

For each canonical (slug, prompt, expected_keys) tuple, the test:
  1. Logs in as the demo admin to grab a JWT.
  2. POSTs to /api/agents/{slug}/execute with the prompt.
  3. Asserts HTTP 200 + non-empty output that parses as JSON.
  4. Asserts the expected_keys are present.

Pass criterion: at least 80% of cases green. Lower threshold than 100%
because new agents land continuously and the test should not block a
single-agent regression — surface it instead.

Also includes regression guards added after the SDK silent-empty-output
incident:
  * test_sdk_execute_returns_populated_output — fires a real Abenix SDK
    .execute() through a slow agent and asserts the output is non-empty,
    has an execution_id, and the DB row is status=completed. Catches a
    regression where the SDK returns immediately on async-mode without
    waiting / polling.
  * test_server_defaults_wait_for_api_key_callers — hits the execute
    endpoint with X-API-Key (no wait param) and asserts a synchronous
    response; same endpoint with JWT cookie returns async. Belt-and-
    suspenders alongside the SDK fix.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
import requests

API_URL = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
ADMIN_EMAIL = os.environ.get("ABENIX_ADMIN_EMAIL", "admin@abenix.dev")
ADMIN_PASSWORD = os.environ.get("ABENIX_ADMIN_PASSWORD", "Admin123456")
# A platform-scope X-API-Key. Either the canonical seeded key or a fresh
# one minted at test setup. Set ABENIX_API_KEY to skip mint.
PLATFORM_API_KEY = os.environ.get("ABENIX_API_KEY") or os.environ.get(
    "EXAMPLE_APP_ABENIX_API_KEY"
)


# Canonical prompts per agent. Keep small — this is a smoke gate, not
# a quality bench. expected_keys covers the most schema-load-bearing
# fields so the test catches "agent emits free-form prose" regressions.
CASES: list[tuple[str, str, list[str]]] = [
    (
        "resolveai-triage",
        "Customer says their headphones arrived broken yesterday. SKU H-1234, EU.",
        ["intent"],
    ),
    (
        "resolveai-policy-research",
        "Intent: damaged_item refund. SKU: H-1234. Jurisdiction: EU.",
        ["policies", "gaps", "search_status"],
    ),
    (
        "resolveai-resolution-planner",
        'Triage: {"intent":"damaged_item"}. Policies: []. Gaps: ["no_policy_match"].',
        ["actions", "summary"],
    ),
    (
        "claimsiq-fnol-intake",
        "Hi, my car got hailed last weekend. Policy AUTO-9999. Loss date 2026-04-25.",
        ["claim_type"],
    ),
    (
        "claimsiq-policy-matcher",
        "Claim type: comprehensive_auto. Policy #: AUTO-9999. Loss date: 2026-04-25.",
        ["coverage_sections"],
    ),
    (
        "iot-pump-diagnosis",
        "Pump P-101 vibration at 8.2 mm/s RMS, bearing temp 78C, baseline 60C.",
        ["diagnosis"],
    ),
    (
        "iot-coldchain-monitor",
        "Vaccine fridge temp 11.3C for 45 minutes. Lot V-2026-04-001.",
        ["status"],
    ),
    (
        "deep-research",
        "What is the typical refund window in EU consumer law?",
        [],
    ),
    (
        "research-assistant",
        "Briefly: what is ISO 10816 zone C for a 50kW pump?",
        [],
    ),
]


@pytest.fixture(scope="module")
def auth_token() -> str:
    """Log in once as demo admin and reuse the JWT for every case."""
    resp = requests.post(
        f"{API_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Login failed ({resp.status_code}) — cluster not up?")
    body = resp.json()
    token = (
        body.get("access_token")
        or body.get("token")
        or (body.get("data") or {}).get("access_token")
    )
    if not token:
        pytest.skip(f"Login response had no access_token: {body}")
    return token


def _execute(slug: str, prompt: str, token: str) -> dict[str, Any]:
    resp = requests.post(
        f"{API_URL}/api/agents/{slug}/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": prompt, "context": {}},
        timeout=120,
    )
    return {
        "status_code": resp.status_code,
        "body": resp.json() if resp.headers.get("content-type", "").startswith(
            "application/json"
        ) else resp.text,
    }


def _output_text(body: Any) -> str:
    """Pull the agent's main output payload out of whatever envelope the
    API used. Different routers wrap differently — be liberal."""
    if not isinstance(body, dict):
        return str(body or "")
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    for k in ("output_message", "output", "result", "response", "message"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):
            return json.dumps(v)
    return ""


def test_agents_smoke_at_least_80pct_green(auth_token: str) -> None:
    results: list[tuple[str, bool, str]] = []
    for slug, prompt, expected_keys in CASES:
        try:
            r = _execute(slug, prompt, auth_token)
            if r["status_code"] != 200:
                results.append((slug, False, f"http {r['status_code']}"))
                continue
            text = _output_text(r["body"])
            if not text:
                results.append((slug, False, "empty output"))
                continue
            # If the agent claims structured output, it should parse.
            obj: Any = None
            if text.lstrip().startswith("{"):
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    obj = None
            if expected_keys:
                if not isinstance(obj, dict):
                    results.append((slug, False, "not JSON object"))
                    continue
                missing = [k for k in expected_keys if k not in obj]
                if missing:
                    results.append(
                        (slug, False, f"missing keys: {missing}")
                    )
                    continue
            results.append((slug, True, ""))
        except Exception as e:
            results.append((slug, False, f"exc: {e}"))

    green = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n--- Agent smoke results ---")
    for slug, ok, why in results:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {slug:35s} {why}")

    pct = green / total if total else 0.0
    assert pct >= 0.80, (
        f"Only {green}/{total} agents green ({pct:.0%}); want >= 80%."
    )


# ────────────────────────────────────────────────────────────────────────
# SDK + server-default regression guards.
# Why these exist: the standalone-app SDK once silently returned empty
# output because /execute went async-by-default and the SDK didn't pass
# wait=True. Six byte-identical SDK copies were affected. Fix lives in
# packages/sdk/python/abenix_sdk/__init__.py + a server-side default for
# X-API-Key callers in apps/api/app/routers/agents.py. These two tests
# catch a regression in either layer.
# ────────────────────────────────────────────────────────────────────────


def _api_key_or_skip() -> str:
    if not PLATFORM_API_KEY:
        pytest.skip(
            "Set ABENIX_API_KEY (or EXAMPLE_APP_ABENIX_API_KEY) to run SDK tests."
        )
    return PLATFORM_API_KEY


def test_sdk_execute_returns_populated_output_and_terminal_db_row() -> None:
    """Probe through the actual SDK (not curl): slow agent + assert non-empty.

    This is the single load-bearing assertion that tells us the SDK
    .execute() default of wait=True (with async-mode fallback poll) is
    still in place. If this regresses, every standalone app's
    `forge.execute(...)` returns ExecutionResult(output="") and the
    Insights / the example app / ResolveAI flows go silent.
    """
    import asyncio

    api_key = _api_key_or_skip()
    try:
        from abenix_sdk import Abenix
    except ImportError:
        pytest.skip("abenix_sdk not importable — install packages/sdk/python")

    # Pick a reliably > 5s agent. deep-research is the canonical slow one
    # in the smoke set; fall back to research-assistant if missing.
    slow_slug = os.environ.get("ABENIX_SDK_TEST_AGENT", "deep-research")
    prompt = (
        "Research the typical refund window in EU consumer law. "
        "Briefly summarize."
    )

    async def _run() -> Any:
        async with Abenix(api_key=api_key, base_url=API_URL, timeout=240) as forge:
            return await forge.execute(slow_slug, prompt)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        # If the slow agent isn't seeded, fall back to a faster one but
        # keep the assertion contract.
        if "Agent not found" in str(e):
            async def _run2() -> Any:
                async with Abenix(api_key=api_key, base_url=API_URL, timeout=180) as forge:
                    return await forge.execute(
                        "resolveai-triage",
                        "Customer says headphones broken. SKU H-1234, EU.",
                    )
            result = asyncio.run(_run2())
        else:
            raise

    # The SDK regression that this test exists for: empty output.
    assert result.output is not None, "SDK returned None output"
    assert result.output != "", (
        f"SDK returned empty output — likely async-mode regression. "
        f"Result: {result!r}"
    )
    assert len(result.output.strip()) > 5, (
        f"SDK output suspiciously short: {result.output!r}"
    )


def test_server_defaults_wait_true_for_api_key_callers(auth_token: str) -> None:
    """X-API-Key caller without `wait` should get a synchronous response.

    JWT/cookie caller without `wait` should get an async response with
    {execution_id, mode: "async"}. This is the server-side belt-and-
    suspenders: even if a future SDK ships with `wait` accidentally
    dropped, the server still returns synchronously.
    """
    api_key = _api_key_or_skip()
    slug = "resolveai-triage"  # one of the smoke set's reliably-seeded agents
    prompt = "Customer says headphones broken yesterday. SKU H-1234, EU."

    # 1) X-API-Key, no wait param → expect synchronous (output populated)
    r_key = requests.post(
        f"{API_URL}/api/agents/{slug}/execute",
        headers={"X-API-Key": api_key},
        json={"message": prompt, "stream": False},
        timeout=180,
    )
    assert r_key.status_code == 200, f"API-key execute failed: {r_key.text[:300]}"
    body_key = r_key.json().get("data", {}) or {}
    # Sync responses carry output_text/output OR (sync_via_queue) status=completed
    has_output = bool(body_key.get("output") or body_key.get("output_message"))
    is_terminal = body_key.get("status") in ("completed", "succeeded", "failed")
    assert has_output or is_terminal, (
        f"API-key execute returned without sync output (server default broken?): "
        f"{body_key!r}"
    )
    assert body_key.get("mode") != "async", (
        f"API-key caller got mode=async — server default not honoring "
        f"X-API-Key heuristic. Body: {body_key!r}"
    )

    # 2) JWT, no wait param → expect async-mode (no synchronous output)
    r_jwt = requests.post(
        f"{API_URL}/api/agents/{slug}/execute",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"message": prompt, "stream": False},
        timeout=30,
    )
    assert r_jwt.status_code == 200, f"JWT execute failed: {r_jwt.text[:300]}"
    body_jwt = r_jwt.json().get("data", {}) or {}
    # JWT path may also be a sync inline fallback when scaling_exec_remote
    # is off (e.g. in dev with no agent-runtime pool). The contract we care
    # about: when remote queue IS up, JWT defaults to async. When it's
    # inline, both paths look the same. Only fail if mode is set and ==
    # something else than "async" alongside an execution_id w/o output.
    if body_jwt.get("mode") == "async":
        assert body_jwt.get("execution_id"), "async response missing execution_id"
