"""The closed loop: device_command policies, rule step chaining, the events stream and the loop tools."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import pytest

from app.routers.telemetry_loop import headline, resolve_refs
from app.services import event_stream as ES
from app.telemetry import agent_commands as P
from app.telemetry.rules import actions as X
from engine.agent_executor import list_tool_classes
from engine.tool_config_prompt import build_tool_config_prompt
from telemetry_fakes import FakeRedis

T = "11111111-1111-1111-1111-111111111111"


# the device_command policy


def test_policy_cleans_with_plain_errors_and_safe_defaults():
    pol, err = P.clean({})
    assert pol["approval"] == "always" and pol["rate_per_minute"] == P.DEFAULT_RATE
    assert pol["assets"] == [] and pol["signals"] == [] and not err
    pol, err = P.clean(
        {
            "assets": "groundwork/ipc-ex1\ntag:haul, groundwork/ipc-ex1",
            "signals": ["Mode/Set", "bad signal"],
            "approval": "sometimes",
            "rate_per_minute": 0,
            "confirm_timeout_ms": 99999,
        }
    )
    assert pol["assets"] == ["groundwork/ipc-ex1", "tag:haul"]
    assert pol["signals"] == ["Mode/Set"]
    assert set(err) == {"signals", "approval", "rate_per_minute", "confirm_timeout_ms"}
    assert pol["rate_per_minute"] == 1 and pol["confirm_timeout_ms"] == P.MAX_CONFIRM_MS


@pytest.mark.parametrize(
    "pattern,key,ok",
    [
        ("groundwork/ipc-ex1", ("groundwork", "ipc-ex1", ""), True),
        ("groundwork/ipc-ex1", ("groundwork", "ipc-ex1", "safety"), True),
        ("groundwork/ipc-ex1", ("groundwork", "ipc-tc1", "safety"), False),
        ("groundwork/ipc-ex1/safety", ("groundwork", "ipc-ex1", "engine"), False),
        ("groundwork/ipc-*", ("groundwork", "ipc-dz1", "blade"), True),
        ("groundwork", ("groundwork", "ipc-dz1", ""), True),
        ("*", ("testbed", "meter-1", "plc"), True),
        ("testbed/*/plc", ("testbed", "meter-1", ""), False),
        ("a/b/c/d", ("a", "b", "c"), False),
    ],
)
def test_asset_patterns(pattern, key, ok):
    assert P.asset_matches(pattern, *key, [], None) is ok


def test_tags_types_and_signals():
    pol, _ = P.clean(
        {"assets": ["tag:Haul", "type:vehicle"], "signals": ["Task/*", "Mode/Set"]}
    )
    assert P.asset_allowed(pol, "g", "ht1", "", ["haul"], None)
    assert P.asset_allowed(pol, "g", "van", "", [], "vehicle")
    assert not P.asset_allowed(pol, "g", "ex1", "", ["dig"], "machine")
    assert P.signal_allowed(pol, "Task/Assign") and P.signal_allowed(pol, "Mode/Set")
    assert not P.signal_allowed(pol, "Safety/Hold")
    msg = P.refusal_signal(pol, "Safety/Hold", "EX1")
    assert msg.startswith("Not sent.") and "Task/*, Mode/Set" in msg


def test_no_policy_refuses_everything_in_plain_words():
    class Agent:
        model_config_ = {"tool_config": {"device_command": {"parameter_defaults": {}}}}

    assert P.policy_of(Agent()) is None
    assert "no command policy" in P.NO_POLICY
    Agent.model_config_ = {
        "tool_config": {
            "device_command": {"parameter_defaults": {"policy": {"assets": ["*"]}}}
        }
    }
    assert P.policy_of(Agent()) == {"assets": ["*"]}


def test_approval_modes_tiers_and_earned_autonomy():
    always, _ = P.clean({"approval": "always"})
    never, _ = P.clean({"approval": "never"})
    tier, _ = P.clean({"approval": "tier", "tier": "high"})
    assert P.approval_needed(always, "allow", False)[0] is True
    assert P.approval_needed(never, "approval", False)[0] is False
    assert P.approval_needed(tier, "approval", False)[0] is True
    assert P.approval_needed(tier, "allow", False)[0] is False
    needs, _, blocked = P.approval_needed(tier, "block", False)
    assert not needs and blocked and "blocks high risk" in blocked
    # a grant lifts the policy's own gate, the autonomy gate decides instead
    needs, why, _ = P.approval_needed(always, "allow", True)
    assert not needs and "Earned Autonomy" in why


def test_an_approval_covers_only_the_command_it_showed():
    payload = {
        "command": {
            "group": "g",
            "node": "n",
            "device": "",
            "signal": "Mode/Set",
            "value": "safe",
        }
    }
    want = dict(payload["command"])
    assert P.same_command(payload, want)
    assert not P.same_command(payload, {**want, "value": "auto"})
    assert not P.same_command(payload, {**want, "node": "other"})
    num = {"command": {**want, "signal": "Setpoint", "value": 42}}
    assert P.same_command(num, {**want, "signal": "Setpoint", "value": "42.0"})
    assert P.same_command(
        {"command": {**want, "value": True}}, {**want, "value": "true"}
    )


def test_policy_reaches_the_prompt_in_words():
    tc = {
        "device_command": {
            "parameter_defaults": {
                "policy": {
                    "assets": ["groundwork/ipc-ex1"],
                    "signals": ["Mode/Set"],
                    "approval": "always",
                    "rate_per_minute": 3,
                }
            }
        }
    }
    out = build_tool_config_prompt("base", tc)
    assert "may command groundwork/ipc-ex1" in out and "approves every command" in out
    assert "policy=" not in out
    out = build_tool_config_prompt(
        "base", {"device_command": {"usage_instructions": "x"}}
    )
    assert "none set yet" in out


# finding assets


ROWS = [
    {
        "key": "g/ex1/",
        "group": "g",
        "node": "ex1",
        "device": "",
        "display_name": "Excavator EX1",
        "tags": ["dig"],
        "type": "machine",
    },
    {
        "key": "g/ex1/safety",
        "group": "g",
        "node": "ex1",
        "device": "safety",
        "display_name": None,
        "tags": [],
        "type": None,
    },
    {
        "key": "g/ht1/",
        "group": "g",
        "node": "ht1",
        "device": "",
        "display_name": "Haul truck 1",
        "tags": ["haul"],
        "type": "vehicle",
    },
    {
        "key": "g/ht2/",
        "group": "g",
        "node": "ht2",
        "device": "",
        "display_name": "Haul truck 2",
        "tags": ["haul"],
        "type": "vehicle",
    },
    {
        "key": "t/meter-1/",
        "group": "t",
        "node": "meter-1",
        "device": "",
        "display_name": None,
        "tags": [],
        "type": None,
    },
]


def test_refs_resolve_by_key_name_and_unique_part():
    found, unknown, amb = resolve_refs(
        ROWS, ["g/ex1/safety", "excavator ex1", "meter-1", "Haul truck", "nope"]
    )
    assert [r["key"] for r in found] == ["g/ex1/safety", "g/ex1/", "t/meter-1/"]
    assert unknown == ["nope"]
    assert amb == {"Haul truck": ["g/ht1/", "g/ht2/"]}


def test_headline_prefers_asked_signals_then_numbers():
    doc = {
        "metrics": [
            {"name": "Node/Uptime_s", "value": 5},
            {"name": "Note", "value": "x"},
        ],
        "devices": [
            {
                "device": "engine",
                "metrics": [{"name": "Engine/Speed_rpm", "value": 1450, "ts": 1}],
            }
        ],
    }
    assert [h["signal"] for h in headline(doc, [])] == [
        "Node/Uptime_s",
        "Engine/Speed_rpm",
    ]
    got = headline(doc, ["Engine/"])
    assert got == [
        {
            "signal": "Engine/Speed_rpm",
            "part": "engine",
            "value": 1450,
            "unit": None,
            "ts": 1,
            "quality": None,
        }
    ]
    assert headline(None, []) == []


# rule steps that chain


def _ctx():
    return {
        "rule": "Pump high",
        "detail": "p is 312",
        "group": "g",
        "node": "ex1",
        "device": "hydraulics",
        "asset": "Excavator EX1 hydraulics",
        "signal": "p",
        "value": 312,
        "steps": [
            {
                "kind": "run",
                "status": "ok",
                "output": {"action": "safe", "level": 3, "list": [7, 8]},
            },
            {"kind": "decision", "status": "ok", "output": True},
        ],
    }


def test_step_references_fill_text_and_keep_types():
    ctx = _ctx()
    assert X.render("{{asset}}: {steps.1.output.action} / {{steps.2.output}}", ctx) == (
        "Excavator EX1 hydraulics: safe / true"
    )
    assert X.resolve_value("{steps.1.output.level}", ctx) == 3
    assert X.resolve_value("{{ steps.1.output.list.1 }}", ctx) == 8
    assert X.resolve_value("{steps.1.output}", ctx) == {
        "action": "safe",
        "level": 3,
        "list": [7, 8],
    }
    assert X.resolve_value("level {steps.1.output.level}", ctx) == "level 3"
    assert X.resolve_value("{steps.9.output}", ctx) is None
    assert X.resolve_value(5, ctx) == 5
    assert X.step_refs("a {steps.1.output} {{steps.3.status}}") == {1, 3}


def test_agent_answers_parse_as_json_when_they_are():
    assert X.parse_output('{"a": 1}') == {"a": 1}
    assert X.parse_output('Done.\n```json\n{"action": "hold"}\n```\nThanks') == {
        "action": "hold"
    }
    assert X.parse_output("  plain words ") == "plain words"
    assert X.parse_output(None) is None


def test_run_message_carries_the_asset_key_history_and_earlier_steps():
    ctx = _ctx()
    ctx["history"] = {
        "minutes": 15,
        "summary": {"first": 250, "last": 312, "min": 248, "max": 315},
    }
    msg = X.run_message({}, ctx)
    assert "key g/ex1/hydraulics" in msg and "p = 312" in msg
    assert "first 250, last 312" in msg and 'Step 1 (run) said: {"action"' in msg
    assert (
        X.run_message({"message": "Look at {{asset}}"}, ctx)
        == "Look at Excavator EX1 hydraulics"
    )


def test_step_input_shows_what_each_step_was_given():
    ctx = _ctx()
    got = X.step_input(
        {"kind": "command", "signal": "Mode/Set", "value": "{steps.1.output.action}"},
        ctx,
    )
    assert got["value"] == "safe" and got["node"] == "ex1"
    got = X.step_input(
        {"kind": "decision", "key": "k", "facts": {"lvl": "{steps.1.output.level}"}},
        ctx,
    )
    assert got == {"key": "k", "facts": {"lvl": 3}}
    assert X.window_of({"kind": "rate", "window_s": 60}) == 60
    assert X.window_of({"kind": "threshold"}) is None


def test_runner_waits_for_the_run_and_reads_its_answer(monkeypatch):
    calls = {"n": 0}

    class Row(tuple):
        pass

    class Result:
        def __init__(self, row):
            self.row = row

        def first(self):
            return self.row

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, q):
            calls["n"] += 1
            if calls["n"] < 3:
                return Result(("running", None, None, None))
            return Result(("completed", '{"action": "hold"}', None, 1200))

    import app.core.deps as deps

    monkeypatch.setattr(deps, "async_session", lambda: DB())
    got = asyncio.run(X.wait_for_run("e1", 5, every=0.01))
    assert got == ("completed", '{"action": "hold"}', None, 1200)
    calls["n"] = 0

    class Never(DB):
        async def execute(self, q):
            return Result(("running", None, None, None))

    monkeypatch.setattr(deps, "async_session", lambda: Never())
    t0 = time.monotonic()
    assert asyncio.run(X.wait_for_run("e1", 0, every=0.01)) is None
    assert time.monotonic() - t0 < 1


# the events stream


def test_types_and_since_parse_with_plain_errors():
    cat = {
        "telemetry.rule_fired": {},
        "execution.completed": {},
        "execution.failed": {},
    }
    assert ES.parse_types("telemetry.rule_fired, execution.*", cat) == (
        ["telemetry.rule_fired", "execution.*"],
        [],
    )
    assert ES.parse_types("nope.*,*", cat)[1] == ["nope.*"]
    assert ES.parse_since("4211") == (4211, None)
    assert ES.parse_since("evt_12") == (12, None)
    i, t = ES.parse_since("2026-10-11T09:00:00Z")
    assert i is None and t == datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        ES.parse_since("yesterday")


def _env(t, **data):
    return {"id": 1, "tenant": T, "type": t, "occurred_at": "x", "data": data}


def test_viewers_only_see_what_they_may():
    class Scope:
        def sees(self, c):
            return c == "mine"

    member = ES.Viewer(T, "u1", False, frozenset({"telemetry.view"}), Scope())
    admin = ES.Viewer(T, "u9", True, frozenset({"*"}))
    assert member.may_see(_env("execution.completed", user_id="u1"))
    assert not member.may_see(_env("execution.completed", user_id="u2"))
    assert admin.may_see(_env("execution.completed", user_id="u2"))
    assert member.may_see(_env("telemetry.rule_fired"))
    assert member.may_see(_env("telemetry.device_online", connection_id="mine"))
    assert not member.may_see(_env("telemetry.device_online", connection_id="theirs"))
    assert member.may_see(_env("approval.requested", requested_by="u1"))
    assert not member.may_see(_env("approval.requested", requested_by="u2"))
    assert not member.may_see(_env("decision.published"))
    assert not member.may_see(_env("something.new"))
    picky = ES.Viewer(T, "u9", True, frozenset({"*"}), types=["telemetry.*"])
    assert not picky.may_see(_env("execution.completed"))


def test_seen_never_repeats_and_stays_bounded():
    s = ES.Seen(cap=3)
    assert s.add(1) and not s.add(1)
    for i in range(2, 6):
        s.add(i)
    assert len(s.ids) == 3 and s.add(1)


def test_sse_frames_carry_the_id_to_resume_from():
    out = ES.sse(
        {"id": 42, "type": "telemetry.rule_fired", "occurred_at": "t", "data": {"a": 1}}
    )
    assert out.startswith("id: 42\nevent: telemetry.rule_fired\ndata: ")
    assert json.loads(out.split("data: ", 1)[1])["data"] == {"a": 1}


def test_hub_hands_events_to_the_right_tenant_and_drops_oldest():
    hub = ES.Hub()
    v = ES.Viewer(T, "u", True, frozenset({"*"}))
    other = ES.Viewer("other", "u", True, frozenset({"*"}))
    hub.viewers[T].add(v)
    hub.viewers["other"].add(other)
    hub.dispatch(_env("telemetry.rule_fired"))
    assert v.queue.qsize() == 1 and other.queue.qsize() == 0
    small = ES.Viewer(T, "u", True, frozenset({"*"}))
    small.queue = asyncio.Queue(1)
    small.offer({"id": 1})
    small.offer({"id": 2})
    assert small.dropped == 1 and small.queue.get_nowait()["id"] == 2


# the agent tools


def test_new_tools_are_registered_and_declared():
    from engine.tools.asset_search import AssetSearchTool
    from engine.tools.device_command import DeviceCommandTool

    names = list_tool_classes()
    assert "asset_search" in names and "device_command" in names
    assert DeviceCommandTool.effect.kind == "control"
    assert DeviceCommandTool.input_schema["required"] == [
        "asset",
        "signal",
        "value",
        "reason",
    ]
    for cls in (AssetSearchTool, DeviceCommandTool):
        assert cls.config_fields and not any(f.required for f in cls.config_fields)


def _run_ctx(monkeypatch):
    from engine.tools import _telemetry_api as api

    monkeypatch.setattr(
        api,
        "run_info",
        lambda: {
            "tenant": T,
            "user_id": "u1",
            "agent_id": "a1",
            "execution_id": "e1",
            "agent_name": "W",
        },
    )


def test_device_command_asks_waits_then_sends(monkeypatch):
    from engine.tools import _telemetry_api as api
    from engine.tools import device_command as D

    _run_ctx(monkeypatch)
    sent = []

    async def call(method, path, *, params=None, body=None, timeout=20):
        sent.append((path, dict(body or {})))
        if path.endswith("/propose"):
            return (
                200,
                {
                    "needs_approval": True,
                    "approval": {"id": "ap1", "expires_seconds": 60},
                    "target": {"name": "EX1"},
                    "governed_by": "policy",
                },
                "",
            )
        if path.endswith("/send"):
            return (
                200,
                {
                    "published": True,
                    "confirmed": True,
                    "approved_by": "ops@x",
                    "approval_id": "ap1",
                    "timings": {"published_at": 5},
                },
                "",
            )
        raise AssertionError(path)

    async def wait_for(aid, limit, eid):
        assert aid == "ap1" and eid == "e1"
        return {
            "status": "approved",
            "signoffs": [{"decision": "approve", "user_email": "ops@x"}],
        }

    monkeypatch.setattr(api, "call", call)
    monkeypatch.setattr(D, "wait_for", wait_for)
    r = asyncio.run(
        D.DeviceCommandTool().execute(
            {
                "asset": "g/ex1",
                "part": "safety",
                "signal": "Mode/Set",
                "value": "safe",
                "reason": "Pressure rose 18%",
            }
        )
    )
    assert not r.is_error, r.content
    out = json.loads(r.content)
    assert out["published"] and out["confirmed"] and out["approved_by"] == "ops@x"
    assert (
        out["timings"]["approval_wait_ms"] is not None
        and out["timings"]["total_ms"] >= 0
    )
    assert sent[0][1]["agent_id"] == "a1" and sent[0][1]["part"] == "safety"
    assert sent[1][1]["approval_id"] == "ap1"
    # the model cannot hand itself a policy
    assert "policy" not in sent[0][1]


def test_device_command_denied_refused_and_test(monkeypatch):
    from engine.tools import _telemetry_api as api
    from engine.tools import device_command as D

    _run_ctx(monkeypatch)

    async def denied_call(method, path, *, params=None, body=None, timeout=20):
        return 200, {"needs_approval": True, "approval": {"id": "ap1"}}, ""

    async def denied(aid, limit, eid):
        return {
            "status": "denied",
            "signoffs": [
                {
                    "decision": "deny",
                    "user_email": "ops@x",
                    "user_name": "Ops Lead",
                    "reason": "Crew on the boom.",
                }
            ],
        }

    monkeypatch.setattr(api, "call", denied_call)
    monkeypatch.setattr(D, "wait_for", denied)
    args = {
        "asset": "g/ex1",
        "signal": "Mode/Set",
        "value": "safe",
        "reason": "why not",
    }
    r = asyncio.run(D.DeviceCommandTool().execute(args))
    assert r.is_error and "Ops Lead denied the command: Crew on the boom." in r.content

    async def refused(method, path, *, params=None, body=None, timeout=20):
        return (
            403,
            {"error_code": "NOT_ALLOWED"},
            "Not sent. This agent may not command EX1.",
        )

    monkeypatch.setattr(api, "call", refused)
    r = asyncio.run(D.DeviceCommandTool().execute(args))
    assert r.is_error and r.content.startswith("Not sent.")

    async def test_run(method, path, *, params=None, body=None, timeout=20):
        assert path.endswith("/propose")
        return 200, {"test": True, "message": "Test run: nothing was sent."}, ""

    monkeypatch.setattr(api, "call", test_run)
    r = asyncio.run(D.DeviceCommandTool().execute(args))
    assert not r.is_error and json.loads(r.content)["test"] is True


def test_device_command_needs_an_agent_run(monkeypatch):
    from engine.tools import _telemetry_api as api
    from engine.tools.device_command import DeviceCommandTool

    monkeypatch.setattr(
        api,
        "run_info",
        lambda: {
            "tenant": T,
            "user_id": "",
            "agent_id": "",
            "execution_id": "",
            "agent_name": "",
        },
    )
    r = asyncio.run(
        DeviceCommandTool().execute(
            {"asset": "a/b", "signal": "s", "value": 1, "reason": "abc"}
        )
    )
    assert r.is_error and "agent's run" in r.content


def test_asset_search_passes_filters_and_explains_empty(monkeypatch):
    from engine.tools import _telemetry_api as api
    from engine.tools.asset_search import AssetSearchTool

    seen = {}

    async def call(method, path, *, params=None, body=None, timeout=20):
        seen.update(params or {})
        return 200, [], ""

    monkeypatch.setattr(api, "call", call)
    r = asyncio.run(
        AssetSearchTool(tenant_id=T).execute(
            {"type": "vehicle", "tag": "haul", "online": True, "signals": ["Engine/"]}
        )
    )
    out = json.loads(r.content)
    assert out["count"] == 0 and "No assets match" in out["message"]
    assert (
        seen["type"] == "vehicle"
        and seen["online"] == "yes"
        and seen["headline_signals"] == "Engine/"
    )


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: r)
    return r


def test_device_state_reads_several_named_assets(monkeypatch, fake_redis):
    from engine.tools import _telemetry_api as api
    from engine.tools.device_state import DeviceStateTool

    now = int(time.time() * 1000)

    async def seed():
        for n, rpm in (("ht1", 1200), ("ht2", 900)):
            await fake_redis.hset(
                f"tel:{T}:g:{n}:", mapping={"_online": "1", "_last_seen": str(now)}
            )
            await fake_redis.sadd(f"tel:{T}:nodedevs:g:{n}", "", "engine")
            await fake_redis.hset(
                f"tel:{T}:g:{n}:engine",
                mapping={
                    "_online": "1",
                    "m:Engine/Speed_rpm": json.dumps(
                        {"v": rpm, "t": "Double", "ts": now}
                    ),
                },
            )

    asyncio.run(seed())

    async def resolve(args):
        assert args["where"] == {"tag": "haul"}
        return (
            [
                {
                    "group": "g",
                    "node": "ht1",
                    "device": "",
                    "name": "Haul truck 1",
                    "key": "g/ht1/",
                },
                {
                    "group": "g",
                    "node": "ht2",
                    "device": "",
                    "name": "Haul truck 2",
                    "key": "g/ht2/",
                },
            ],
            "",
            {"unknown": [], "ambiguous": {}},
        )

    monkeypatch.setattr(api, "resolve", resolve)
    r = asyncio.run(
        DeviceStateTool(tenant_id=T).execute(
            {"where": {"tag": "haul"}, "metrics": ["Engine/Speed_rpm"]}
        )
    )
    out = json.loads(r.content)
    assert out["count"] == 2
    speeds = {a["name"]: a["devices"][0]["metrics"][0]["value"] for a in out["assets"]}
    assert speeds == {"Haul truck 1": 1200, "Haul truck 2": 900}

    async def none(args):
        return [], "No assets to read: no asset called X.", {}

    monkeypatch.setattr(api, "resolve", none)
    r = asyncio.run(DeviceStateTool(tenant_id=T).execute({"asset": "X"}))
    assert r.is_error and "no asset called X" in r.content


def test_a_value_already_reported_counts_as_confirmed():
    from app.routers.telemetry_loop import settle_confirmation

    sent = {"published": True, "confirmed": False, "confirm_note": "did not report"}
    got = settle_confirmation(sent, {"value": "safe"}, "safe", "Mode/Set")
    assert got["confirmed"] is True and got["already_at_value"] is True
    assert "already read safe" in got["confirm_note"]
    assert settle_confirmation(sent, {"value": 50.0}, 50, "Setpoint_kW")["confirmed"]
    assert settle_confirmation(sent, {"value": "auto"}, "safe", "Mode/Set") == sent
    assert settle_confirmation(sent, None, "safe", "Mode/Set") == sent
    ok = {"published": True, "confirmed": True}
    assert settle_confirmation(ok, {"value": "safe"}, "safe", "Mode/Set") == ok
    unsent = {"published": False}
    assert settle_confirmation(unsent, {"value": "safe"}, "safe", "Mode/Set") == unsent


# text with any characters, approval wake-up and who decided

TEXT = "Oil 76.5°C, drift 3 µm, cost 12 € 🛑"


def test_unicode_survives_the_tool_the_api_and_the_stream(monkeypatch):
    import httpx

    from app.routers.telemetry_loop import command_summary
    from engine.tools import _telemetry_api as api

    s = command_summary("Watcher", "Mode/Set", "auto", "safe", "EX1 µ-site", TEXT)
    assert TEXT in s and "µ-site" in s and "Â" not in s
    out = ES.sse(
        {
            "id": 1,
            "type": "telemetry.command_sent",
            "occurred_at": "t",
            "data": {"reason": TEXT},
        }
    )
    assert json.loads(out.split("data: ", 1)[1])["data"]["reason"] == TEXT
    assert out.isascii()

    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content.decode("utf-8"))
        body = json.dumps({"data": {"reason": TEXT}}, ensure_ascii=False).encode(
            "utf-8"
        )
        return httpx.Response(
            200, content=body, headers={"content-type": "application/json"}
        )

    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(api, "headers", lambda: {})
    status, data, _ = asyncio.run(api.call("POST", "/x", body={"reason": TEXT}))
    assert status == 200 and seen["body"]["reason"] == TEXT and data["reason"] == TEXT


def test_the_sdk_stream_reads_utf8_even_without_a_charset():
    import sys
    from pathlib import Path

    import httpx

    sys.path.insert(
        0, str(Path(__file__).resolve().parents[2] / "packages" / "sdk" / "python")
    )
    from abenix_sdk import Abenix

    raw = json.dumps(
        {"id": 7, "type": "telemetry.command_sent", "data": {"reason": TEXT}},
        ensure_ascii=False,
    )
    frame = f"id: 7\nevent: telemetry.command_sent\ndata: {raw}\n\n".encode("utf-8")

    def handler(req):
        return httpx.Response(
            200, content=frame, headers={"content-type": "text/event-stream"}
        )

    async def go():
        forge = Abenix(api_key="af_test", base_url="http://x")
        forge._http = httpx.AsyncClient(
            base_url="http://x", transport=httpx.MockTransport(handler)
        )
        async for ev in forge.events.stream(
            ["telemetry.command_sent"], reconnect=False
        ):
            return ev

    ev = asyncio.run(go())
    assert ev["data"]["reason"] == TEXT


def test_resolved_events_say_who_decided_and_when():
    signoffs = [
        {
            "user_id": "u7",
            "user_name": "Ops Lead",
            "user_email": "ops@x",
            "decision": "approve",
        }
    ]
    data = ES.decider(
        {"approval_id": "a"}, signoffs, datetime(2026, 10, 12, 1, tzinfo=timezone.utc)
    )
    assert data["decided_by"] == {"id": "u7", "name": "Ops Lead", "email": "ops@x"}
    assert data["decided_at"].startswith("2026-10-12T01:00")
    kept = ES.decider(
        {"decided_by": {"id": "u7", "name": "Ops Lead"}, "decided_at": "t"},
        signoffs,
        None,
    )
    assert kept["decided_by"]["email"] == "ops@x" and kept["decided_at"] == "t"
    assert "decided_by" not in ES.decider({}, [], None)
    env = {"id": 1, "type": "approval.resolved", "data": data}
    member = ES.Viewer(T, "u1", False, frozenset({"approvals.sign"}))
    assert "email" not in member.shape(env)["data"]["decided_by"]
    assert member.shape(env)["data"]["decided_by"]["name"] == "Ops Lead"
    assert (
        ES.Viewer(T, "u7", False, frozenset()).shape(env)["data"]["decided_by"]["email"]
        == "ops@x"
    )
    assert ES.Viewer(T, "u9", True, frozenset({"*"})).shape(env) is env


def test_a_decision_wakes_the_waiting_command(monkeypatch):
    from app.routers import approvals as AP
    from engine.tools import _telemetry_api as api
    from engine.tools import approval_gate as ag
    from engine.tools import device_command as D

    fake = FakeRedis()
    import app.routers.telemetry as TR

    monkeypatch.setattr(TR, "redis", lambda: fake)
    asyncio.run(AP.wake_waiters("ap1", "approved"))
    assert fake.published == [(D.wake_channel("ap1"), "approved")]
    assert AP.wake_channel("ap1") == D.wake_channel("ap1")

    state = {"status": "pending"}

    class PubSub:
        def __init__(self):
            self.n = 0

        async def subscribe(self, ch):
            assert ch == D.wake_channel("ap1")

        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            self.n += 1
            if self.n == 1:
                await asyncio.sleep(0.05)
                state["status"] = "approved"
                return {"type": "message", "data": "approved"}
            await asyncio.sleep(timeout or 0)
            return None

        async def aclose(self):
            pass

    class R:
        def pubsub(self):
            return PubSub()

        async def aclose(self):
            pass

    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: R())

    async def call(method, path, *, params=None, body=None, timeout=20):
        return 200, {"id": "ap1", "status": state["status"]}, ""

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(api, "call", call)
    monkeypatch.setattr(ag, "_mark_waiting", nothing)
    monkeypatch.setattr(ag, "_clear_waiting", nothing)
    monkeypatch.setattr(D, "POLL_S", 5.0)
    t0 = time.monotonic()
    got = asyncio.run(D.wait_for("ap1", 60, "e1"))
    assert got["status"] == "approved"
    assert time.monotonic() - t0 < 1.0, "woke on the message, not the 5 s poll"


def test_the_send_after_an_approval_names_the_asset_by_key(monkeypatch):
    from engine.tools import _telemetry_api as api
    from engine.tools import device_command as D

    _run_ctx(monkeypatch)
    sent = []

    async def call(method, path, *, params=None, body=None, timeout=20):
        sent.append((path, dict(body or {})))
        if path.endswith("/propose"):
            return (
                200,
                {
                    "needs_approval": True,
                    "approval": {"id": "ap1"},
                    "target": {
                        "group": "g",
                        "node": "ex1",
                        "device": "safety",
                        "name": "EX1",
                    },
                },
                "",
            )
        return 200, {"published": True, "confirmed": True, "timings": {}}, ""

    async def approved(aid, limit, eid):
        return {"status": "approved", "signoffs": []}

    monkeypatch.setattr(api, "call", call)
    monkeypatch.setattr(D, "wait_for", approved)
    r = asyncio.run(
        D.DeviceCommandTool().execute(
            {
                "asset": "Excavator EX1",
                "signal": "Mode/Set",
                "value": "safe",
                "reason": TEXT,
            }
        )
    )
    assert not r.is_error
    send = sent[1][1]
    assert send["asset"] is None and (send["group"], send["node"], send["part"]) == (
        "g",
        "ex1",
        "safety",
    )
    assert send["reason"] == TEXT


def test_only_machine_operators_decide_command_approvals():
    from types import SimpleNamespace

    from app.core.approvers import can_sign, eligible_from, required_capabilities

    assert "telemetry.command" in required_capabilities(None, "telemetry.command")
    # a creator signs ordinary approvals by role, not machine commands
    assert can_sign("creator", frozenset({"approvals.sign"}), None, "agent.thing")
    assert not can_sign(
        "creator", frozenset({"approvals.sign"}), None, "telemetry.command"
    )
    assert can_sign(
        "user",
        frozenset({"approvals.sign", "telemetry.command"}),
        None,
        "telemetry.command",
    )
    assert can_sign("admin", frozenset({"*"}), None, "telemetry.command")
    people = [
        (SimpleNamespace(id="req", role="admin"), frozenset({"*"})),
        (
            SimpleNamespace(id="ops", role="user"),
            frozenset({"approvals.sign", "telemetry.command"}),
        ),
        (SimpleNamespace(id="creator", role="creator"), frozenset({"approvals.sign"})),
        (SimpleNamespace(id="member", role="user"), frozenset({"telemetry.view"})),
    ]
    told = [u.id for u in eligible_from(people, None, "telemetry.command", "req")]
    assert told == ["ops"]
    # other kinds reach whoever can sign them, never every member
    told = [u.id for u in eligible_from(people, None, "agent.thing", "req")]
    assert "member" not in told and "creator" in told


# what the approver sees about why the agent asked


def test_text_and_on_off_signals_read_as_states():
    from app.routers.telemetry_loop import is_state, state_timeline

    assert is_state("safe", {"value": "auto"}) and is_state(True, None)
    assert not is_state(42, {"value": 50.0}) and not is_state("42", None)
    pts = [
        {"t": 1, "avg": None, "txt": "auto"},
        {"t": 2, "avg": None, "txt": "auto"},
        {"t": 3, "avg": None, "txt": "safe"},
        {"t": 4, "avg": None},
        {"t": 5, "avg": None, "txt": "auto"},
    ]
    got = state_timeline(pts, {"value": "auto", "ts": 9})
    assert [s["value"] for s in got] == ["auto", "safe", "auto"]
    on_off = state_timeline(
        [{"t": 1, "avg": 0.0}, {"t": 2, "avg": 1.0}], {"value": False, "ts": 3}
    )
    assert [s["value"] for s in on_off] == [False, True, False]
    # nothing in history still shows the state it is in
    assert state_timeline([], {"value": "safe", "ts": 5}) == [{"t": 5, "value": "safe"}]


def test_signal_names_marks_and_units_read_plainly():
    from app.routers.telemetry_loop import marks_of, unit_of, words

    assert words("Hydraulics/OilTemp_C") == "Hydraulics oil temp"
    assert words("Setpoint_kW") == "Setpoint"
    assert words("Engine/Speed_rpm") == "Engine speed"
    assert unit_of("Hydraulics/OilTemp_C") == "C" and unit_of("Mode/Set") is None
    assert marks_of({"kind": "threshold", "op": ">", "value": 75}) == [
        {"label": "fires above 75", "value": 75, "kind": "limit"}
    ]
    assert [m["label"] for m in marks_of({"kind": "range", "min": 10, "max": 20})] == [
        "fires below 10",
        "fires above 20",
    ]
    assert marks_of({"kind": "stale"}) == []


def test_evidence_charts_the_firing_signal_else_what_was_read(monkeypatch):
    from types import SimpleNamespace

    from app.routers import telemetry_loop as L

    pts = [
        {"t": 1, "avg": 70.0, "min": 69.0, "max": 71.0},
        {"t": 2, "avg": 76.5, "min": 76.0, "max": 77.0},
    ]

    async def hist(tenant, g, n, d, signal, minutes=15):
        if signal == "Mode/Set":
            return {"minutes": 15, "points": [{"t": 1, "avg": None, "txt": "auto"}]}
        return {"minutes": 15, "points": pts, "summary": {"last": 76.5}}

    class DB:
        async def get(self, model, key):
            return SimpleNamespace(
                condition={"kind": "threshold", "op": ">", "value": 75}
            )

    firing = SimpleNamespace(
        signal="Hydraulics/OilTemp_C",
        grp="groundwork",
        node="ipc-ex1",
        device="hydraulics",
        rule_id="r1",
        rule_name="EX1 oil hot",
        detail="OilTemp is 76.5, above 75.",
        value=76.5,
        fired_at=None,
    )

    async def fired(db, tenant, eid):
        return firing

    monkeypatch.setattr(L, "recent_history", hist)
    monkeypatch.setattr(L, "firing_of", fired)
    user = SimpleNamespace(tenant_id=T)
    c = {"signal": "Mode/Set"}
    body = SimpleNamespace(execution_id="e1", read=[])
    ev = asyncio.run(L.gather_evidence(DB(), user, c, body))
    assert len(ev) == 1 and ev[0]["source"] == "firing"
    assert ev[0]["title"] == "Why it asked: Hydraulics oil temp, last 15 minutes"
    assert (
        ev[0]["marks"] == [{"label": "fires above 75 °C", "value": 75, "kind": "limit"}]
        and ev[0]["unit"] == "C"
    )

    async def none(db, tenant, eid):
        return None

    monkeypatch.setattr(L, "firing_of", none)
    read = [
        SimpleNamespace(group="g", node="n", device="", signal="Mode/Set"),
        SimpleNamespace(
            group="g", node="n", device="engine", signal="Engine/Speed_rpm"
        ),
        SimpleNamespace(
            group="g", node="n", device="hydraulics", signal="Hydraulics/OilTemp_C"
        ),
        SimpleNamespace(group="g", node="n", device="x", signal="Other_C"),
    ]
    ev = asyncio.run(
        L.gather_evidence(DB(), user, c, SimpleNamespace(execution_id="e2", read=read))
    )
    assert [e["signal"] for e in ev] == ["Engine/Speed_rpm", "Hydraulics/OilTemp_C"]
    assert ev[0]["title"].startswith("What it read: Engine speed")


def test_the_run_remembers_what_the_agent_read(monkeypatch):
    from engine.tools import _telemetry_api as api

    _run_ctx(monkeypatch)
    api._reads.clear()
    api.note_read(
        "g",
        "n",
        "hydraulics",
        ["Hydraulics/OilTemp_C", "Engine/", "Gnss*", "Hydraulics/OilTemp_C"],
    )
    assert api.reads_of("e1") == [
        {
            "group": "g",
            "node": "n",
            "device": "hydraulics",
            "signal": "Hydraulics/OilTemp_C",
        }
    ]
    assert api.reads_of("other") == []


def test_every_rule_kind_draws_a_line_or_says_why_not():
    from app.routers.telemetry_loop import rule_lines

    dev = rule_lines(
        {
            "kind": "deviation",
            "mode": "ratio",
            "direction": "up",
            "threshold": 1.15,
            "window_s": 300,
            "baseline_s": 1800,
        },
        1.17,
        "Hydraulics/OilTemp_C on EX1 ran 16.5% above its level over the last 30 min, the last 5 min (mean 64.9 against 55.7).",
        1000,
        "C",
    )
    assert dev["marks"][0] == {
        "label": "normal 55.7 °C, last 30 min",
        "value": 55.7,
        "kind": "normal",
    }
    assert (
        dev["marks"][1]["label"] == "fires above 64.1 °C"
        and dev["marks"][1]["kind"] == "limit"
    )
    z = rule_lines(
        {
            "kind": "deviation",
            "mode": "zscore",
            "direction": "either",
            "threshold": 2,
            "baseline_s": 600,
        },
        2.5,
        "moved 2.5 standard deviations above its last 10 min over the last 5 min (mean 70 against 60)",
    )
    assert [m["value"] for m in z["marks"]] == [60.0, 68.0, 52.0]
    rng = rule_lines({"kind": "range", "min": 10, "max": 20}, unit="bar")
    assert [m["label"] for m in rng["marks"]] == [
        "fires below 10 bar",
        "fires above 20 bar",
    ]
    rate = rule_lines({"kind": "rate", "limit": 5, "per": "m", "window_s": 60})
    assert rate["marks"] == [] and "faster than 5 a minute" in rate["caption"]
    stale = rule_lines({"kind": "stale", "seconds": 30}, fired_at_ms=100_000)
    assert stale["gap"] == {"from": 70_000, "to": 100_000, "label": "no data for 30 s"}
    geo = rule_lines({"kind": "geofence", "on": "exit", "zone": "the haul road"})
    assert geo["caption"].startswith("Fires when it leaves the haul road")
    cnt = rule_lines({"kind": "count", "count": 3, "window_s": 600})
    assert cnt["caption"] == "Fires when it happens more than 3 times in 10 min."
    st = rule_lines({"kind": "state", "op": "equals", "equals": "fault"})
    assert "is fault" in st["caption"]
    # a deviation with no recorded means still explains itself
    bare = rule_lines(
        {"kind": "deviation", "threshold": 1.2, "window_s": 300, "baseline_s": 1800},
        None,
        "",
    )
    assert bare["marks"] == [] and bare["caption"]


def test_the_state_it_is_in_says_since_when():
    from app.routers.telemetry_loop import state_timeline

    got = state_timeline(
        [{"t": 1, "avg": None, "txt": "auto"}, {"t": 2, "avg": None, "txt": "hold"}],
        {"value": "hold", "ts": 9},
    )
    assert got == [{"t": 1, "value": "auto", "before": True}, {"t": 2, "value": "hold"}]
    assert state_timeline([], {"value": "auto", "ts": 7}) == [{"t": 7, "value": "auto"}]
