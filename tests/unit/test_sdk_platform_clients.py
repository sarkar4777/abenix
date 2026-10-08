"""Python SDK: decision lifecycle, Source Watch, events and identity calls, against a mocked transport."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "sdk" / "python")
)

from abenix_sdk import (  # noqa: E402
    Abenix,
    AbenixDecisionError,
    AbenixError,
    EventsClient,
)


def _client(handler) -> tuple[Abenix, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    sdk = Abenix(api_key="af_test", base_url="http://abenix.test")
    sdk._http = httpx.AsyncClient(
        base_url="http://abenix.test",
        headers={"X-API-Key": "af_test"},
        transport=httpx.MockTransport(wrapped),
    )
    sdk.http = sdk._http
    return sdk, seen


def _ok(data, status=200):
    return httpx.Response(status, json={"data": data, "error": None})


def _body(req: httpx.Request):
    return json.loads(req.content or b"{}")


def test_draft_save_sends_etag_and_only_given_fields():
    sdk, seen = _client(lambda r: _ok({"version": 3, "etag": "8", "problems": []}))
    out = asyncio.run(
        sdk.decisions.save_draft(
            "k", 3, etag="7", valid_from="2026-01-01", change_note="Threshold"
        )
    )
    assert out["etag"] == "8"
    req = seen[0]
    assert req.method == "PUT" and req.url.path == "/api/decisions/k/versions/3"
    assert req.headers["If-Match"] == "7"
    body = _body(req)
    assert body["valid_from"] == "2026-01-01" and body["change_note"] == "Threshold"
    assert "authoring" not in body and "provenance" not in body


def test_lifecycle_paths():
    sdk, seen = _client(lambda r: _ok({"ok": True}))

    async def go():
        await sdk.decisions.new_draft("k", note="n")
        await sdk.decisions.import_rules(
            "k", 2, [{"ruleKey": "a", "then": {"x": 1}}], mode="replace", etag="3"
        )
        await sdk.decisions.propose("k", 2, note="why")
        await sdk.decisions.withdraw("k", 2)
        await sdk.decisions.publish_plan("k", 2)
        await sdk.decisions.diff("k", 1, 2)
        await sdk.decisions.update("k", risk_tier="high")
        await sdk.decisions.retire("k", 1)

    asyncio.run(go())
    got = [(r.method, r.url.path) for r in seen]
    assert got == [
        ("POST", "/api/decisions/k/versions"),
        ("POST", "/api/decisions/k/import"),
        ("POST", "/api/decisions/k/versions/2/propose"),
        ("POST", "/api/decisions/k/versions/2/withdraw"),
        ("GET", "/api/decisions/k/versions/2/publish-plan"),
        ("GET", "/api/decisions/k/diff"),
        ("PATCH", "/api/decisions/k"),
        ("POST", "/api/decisions/k/versions/1/retire"),
    ]
    assert _body(seen[1]) == {
        "payload": [{"ruleKey": "a", "then": {"x": 1}}],
        "mode": "replace",
        "version": 2,
    }
    assert seen[1].headers["If-Match"] == "3"
    assert dict(seen[5].url.params) == {"a": "1", "b": "2"}
    assert _body(seen[6]) == {"risk_tier": "high"}


def test_import_rejects_unknown_mode():
    sdk, _ = _client(lambda r: _ok({}))
    with pytest.raises(ValueError):
        asyncio.run(sdk.decisions.import_rules("k", 1, [], mode="append"))


def test_decision_errors_carry_code_and_details():
    def h(r):
        return httpx.Response(
            422,
            json={
                "data": None,
                "error": {
                    "message": "Not ready",
                    "code": 422,
                    "error_code": "VALIDATION_FAILED",
                    "details": {"ok": False},
                },
            },
        )

    sdk, _ = _client(h)
    with pytest.raises(AbenixDecisionError) as e:
        asyncio.run(sdk.decisions.propose("k", 2))
    assert e.value.status == 422 and e.value.code == "VALIDATION_FAILED"
    assert e.value.details == {"ok": False}
    assert isinstance(e.value, AbenixError)


def test_fastapi_detail_errors_are_readable():
    sdk, _ = _client(
        lambda r: httpx.Response(
            403, json={"detail": "This needs the sources.manage capability"}
        )
    )
    with pytest.raises(AbenixError) as e:
        asyncio.run(sdk.sources.create("Carrier tariff", "https://carrier.example/x"))
    assert e.value.status == 403 and "sources.manage" in str(e.value)

    sdk, _ = _client(
        lambda r: httpx.Response(422, json={"detail": [{"msg": "field required"}]})
    )
    with pytest.raises(AbenixError) as e:
        asyncio.run(sdk.sources.get("x"))
    assert "field required" in str(e.value)


def test_sources_calls():
    sdk, seen = _client(lambda r: _ok([] if r.method == "GET" else {"id": "s1"}))

    async def go():
        await sdk.sources.create(
            "Carrier tariff page",
            "https://carrier.example/tariff",
            tags=["tariff"],
            cadence_minutes=1440,
        )
        await sdk.sources.check_now("s1")
        await sdk.sources.changes(limit=5)
        await sdk.sources.change("c1")
        await sdk.sources.source_changes("s1")
        await sdk.sources.snapshot("p1", full=True)
        await sdk.sources.pause("s1", "maintenance")
        await sdk.sources.update("s1", cadence_minutes=60)

    asyncio.run(go())
    create = _body(seen[0])
    assert (
        create["tags"] == ["tariff"]
        and create["cadence_minutes"] == 1440
        and create["kind"] == "html"
    )
    assert [(r.method, r.url.path) for r in seen[1:]] == [
        ("POST", "/api/sources/s1/check-now"),
        ("GET", "/api/sources/changes"),
        ("GET", "/api/sources/changes/c1"),
        ("GET", "/api/sources/s1/changes"),
        ("GET", "/api/sources/snapshots/p1"),
        ("POST", "/api/sources/s1/pause"),
        ("PATCH", "/api/sources/s1"),
    ]
    assert seen[5].url.params["full"] == "true"


def test_events_subscribe_and_verify():
    sdk, seen = _client(lambda r: _ok({"id": "w1", "signing_secret": "sek"}, 201))
    sub = asyncio.run(
        sdk.events.subscribe(
            ["decision.published"],
            url="https://app.example/hook",
            name="impact",
            filter={"decision_key": ["a", "b"]},
        )
    )
    assert sub["signing_secret"] == "sek"
    body = _body(seen[0])
    assert body == {
        "events": ["decision.published"],
        "name": "impact",
        "target_type": "webhook",
        "url": "https://app.example/hook",
        "filter": {"decision_key": ["a", "b"]},
    }
    raw = b'{"type":"decision.published"}'
    sig = "sha256=" + hmac.new(b"sek", raw, hashlib.sha256).hexdigest()
    assert EventsClient.verify_signature("sek", raw, sig)
    assert EventsClient.verify_signature("sek", raw.decode(), sig)
    assert not EventsClient.verify_signature("sek", raw + b" ", sig)
    assert not EventsClient.verify_signature("", raw, sig)
    assert not EventsClient.verify_signature("sek", raw, None)
    with pytest.raises(ValueError):
        asyncio.run(sdk.events.subscribe([], url="https://x"))


def test_return_for_changes_needs_a_reason():
    sdk, seen = _client(lambda r: _ok({"status": "returned"}))
    with pytest.raises(ValueError):
        asyncio.run(sdk.approvals.return_for_changes("a1", "  "))
    out = asyncio.run(sdk.approvals.return_for_changes("a1", "Cite the article"))
    assert out["status"] == "returned"
    assert _body(seen[0]) == {"decision": "return", "reason": "Cite the article"}


def test_agents_by_slug_and_identity():
    def h(r):
        if r.url.path == "/api/agents/by-slug/missing":
            return httpx.Response(
                404,
                json={
                    "data": None,
                    "error": {"message": "Agent not found", "code": 404},
                },
            )
        if r.url.path == "/api/me/permissions":
            return _ok({"email": "a@b.c", "capabilities": ["approvals.sign"]})
        return _ok({"id": "1", "slug": "found"})

    sdk, seen = _client(h)

    async def go():
        assert await sdk.agents.by_slug("missing") is None
        assert (await sdk.agents.by_slug("found"))["id"] == "1"
        await sdk.agents.create({"name": "A", "slug": "a"})
        await sdk.agents.update("1", {"status": "active"})
        perms = await sdk.permissions()
        assert "approvals.sign" in perms["capabilities"]

    asyncio.run(go())
    assert [(r.method, r.url.path) for r in seen[2:4]] == [
        ("POST", "/api/agents"),
        ("PUT", "/api/agents/1"),
    ]


def test_actions_propose_wait_executed_outcome():
    waits = iter(
        [
            {"action_id": "a1", "decision": "wait", "status": "pending"},
            {
                "action_id": "a1",
                "decision": "run",
                "status": "edited",
                "arguments": {"setpoint_bar": 4.4},
            },
        ]
    )

    def h(r):
        if r.url.path == "/api/autonomy/actions/propose":
            return _ok({"action_id": "a1", "decision": "wait", "approval_id": "p1"}, 201)
        if r.url.path.endswith("/wait"):
            return _ok(next(waits))
        return _ok({"id": "a1", "status": "executed"})

    sdk, seen = _client(h)

    async def go():
        d = await sdk.actions.propose(
            "sample_plant.set_setpoint",
            {"setpoint_bar": 4.6},
            target="plant-1",
            intent="Pressure is low",
            prediction={"metric": "pressure_bar", "value": 4.5, "low": 4.4, "high": 4.6},
        )
        assert d["decision"] == "wait"
        w = await sdk.actions.wait("a1", timeout_seconds=150)
        assert w["decision"] == "run" and w["arguments"] == {"setpoint_bar": 4.4}
        await sdk.actions.executed("a1", True, result_preview="ok")
        await sdk.actions.report_outcome("a1", 4.47, note="read from SCADA")
        await sdk.actions.get("a1")

    asyncio.run(go())
    body = _body(seen[0])
    assert body["action_key"] == "sample_plant.set_setpoint"
    assert body["target"] == "plant-1" and body["prediction"]["high"] == 4.6
    assert "agent_id" not in body
    assert seen[1].url.params["timeout_s"] == "120"
    assert seen[2].url.params["timeout_s"] == "30"
    assert [(r.method, r.url.path) for r in seen[3:]] == [
        ("POST", "/api/autonomy/actions/a1/executed"),
        ("POST", "/api/autonomy/actions/a1/outcome"),
        ("GET", "/api/autonomy/actions/a1"),
    ]
    assert _body(seen[3]) == {"ok": True, "result_preview": "ok"}
    assert _body(seen[4]) == {"value": 4.47, "source": "api", "note": "read from SCADA"}


def test_actions_harm_needs_a_note_and_errors_carry_code():
    sdk, seen = _client(
        lambda r: httpx.Response(
            404,
            json={
                "data": None,
                "error": {"message": "No such action type", "error_code": "UNKNOWN_ACTION"},
            },
        )
    )
    with pytest.raises(ValueError):
        asyncio.run(sdk.actions.flag_harm("a1", "  "))
    assert seen == []
    with pytest.raises(AbenixError) as e:
        asyncio.run(sdk.actions.propose("nope", {}))
    assert e.value.status == 404 and e.value.code == "UNKNOWN_ACTION"


def test_autonomy_reads_and_edited_approval():
    sdk, seen = _client(lambda r: _ok({"items": [], "next_before": None}))

    async def go():
        await sdk.autonomy.overview()
        await sdk.autonomy.grant("g1")
        await sdk.autonomy.grant_actions("g1", status="executed", limit=10, before="x")
        await sdk.approvals.approve("p1", edited_arguments={"setpoint_bar": 4.4})

    asyncio.run(go())
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/api/autonomy/overview"),
        ("GET", "/api/autonomy/grants/g1"),
        ("GET", "/api/autonomy/grants/g1/actions"),
        ("POST", "/api/approvals/p1/signoff"),
    ]
    assert dict(seen[2].url.params) == {"limit": "10", "status": "executed", "before": "x"}
    assert _body(seen[3])["edited_arguments"] == {"setpoint_bar": 4.4}
