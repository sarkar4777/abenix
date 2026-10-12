"""Python SDK: signal rules and the asset registry hit the routes with the shapes they take."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "sdk" / "python")
)

from abenix_sdk import Abenix, AbenixError  # noqa: E402


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


def test_rule_lifecycle_calls():
    sdk, seen = _client(lambda r: _ok({"id": "r1"}))
    t = sdk.telemetry
    scope = {
        "kind": "asset",
        "group": "groundwork",
        "node": "ipc-ex1",
        "device": "hydraulics",
    }
    cond = {
        "kind": "threshold",
        "signal": "Hydraulics/Pump1Pressure_bar",
        "op": ">",
        "value": 300,
    }

    async def go():
        await t.create_rule("EX1 pump", scope, cond, [{"kind": "alert"}], cooldown_s=30)
        await t.preview_rule(scope, cond, hours=6)
        await t.update_rule("r1", enabled=False)
        await t.test_rule("r1")
        await t.rule("r1")
        await t.rules(q="pump")
        await t.rule_signals("groundwork", "ipc-ex1", device="*")
        await t.rule_options()
        await t.set_rules_mode(None)
        await t.rules_mode()
        await t.delete_rule("r1")

    asyncio.run(go())
    calls = [(r.method, r.url.path) for r in seen]
    assert calls == [
        ("POST", "/api/telemetry/rules"),
        ("POST", "/api/telemetry/rules/preview"),
        ("PATCH", "/api/telemetry/rules/r1"),
        ("POST", "/api/telemetry/rules/r1/test"),
        ("GET", "/api/telemetry/rules/r1"),
        ("GET", "/api/telemetry/rules"),
        ("GET", "/api/telemetry/rules/signals"),
        ("GET", "/api/telemetry/rules/options"),
        ("PUT", "/api/telemetry/rules/mode"),
        ("GET", "/api/telemetry/rules/mode"),
        ("DELETE", "/api/telemetry/rules/r1"),
    ]
    body = json.loads(seen[0].content)
    assert (
        body["cooldown_s"] == 30
        and body["actions"] == [{"kind": "alert"}]
        and body["severity"] == "warning"
    )
    assert json.loads(seen[1].content)["hours"] == 6
    assert json.loads(seen[2].content) == {"enabled": False}
    assert seen[6].url.params["device"] == "*"
    assert json.loads(seen[8].content) == {"mode": None}


def test_asset_calls_escape_the_path_and_send_the_whole_entry():
    sdk, seen = _client(lambda r: _ok({"removed": True}))
    t = sdk.telemetry

    async def go():
        await t.assets(type="machine", status="unregistered", parts=True)
        await t.asset("fleet", "van 17")
        await t.update_asset(
            "fleet",
            "van 17",
            display_name="Van 17",
            type="vehicle",
            tags=["city"],
            fields={"plate": "AB12"},
        )
        await t.delete_asset("fleet", "van 17", device="gps")
        await t.import_assets("group,node\nfleet,van-18\n")
        await t.asset_facets()

    asyncio.run(go())
    assert (
        seen[0].url.params["type"] == "machine"
        and seen[0].url.params["parts"] == "true"
    )
    assert seen[1].url.raw_path.startswith(b"/api/telemetry/assets/fleet/van%2017")
    assert json.loads(seen[2].content) == {
        "display_name": "Van 17",
        "type": "vehicle",
        "tags": ["city"],
        "team_id": None,
        "location": None,
        "fields": {"plate": "AB12"},
    }
    assert seen[3].method == "DELETE" and seen[3].url.params["device"] == "gps"
    assert json.loads(seen[4].content)["dry_run"] is True


def test_field_problems_come_back_as_an_error_with_details():
    def bad(req):
        return httpx.Response(
            422,
            json={
                "data": None,
                "error": {
                    "message": "Pick the signal to watch.",
                    "error_code": "VALIDATION_ERROR",
                    "details": {
                        "fields": {"condition.signal": "Pick the signal to watch."}
                    },
                },
            },
        )

    sdk, _ = _client(bad)
    with pytest.raises(AbenixError) as e:
        asyncio.run(
            sdk.telemetry.create_rule("x", {"kind": "asset"}, {"kind": "threshold"})
        )
    assert e.value.status == 422 and e.value.code == "VALIDATION_ERROR"
    assert "condition.signal" in e.value.details["fields"]
