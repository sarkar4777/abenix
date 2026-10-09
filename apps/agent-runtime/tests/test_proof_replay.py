"""A proof replay never runs an effect tool for real, whatever the agent's grant says."""

from __future__ import annotations

import json
from typing import Any

import pytest

from engine import autonomy, governance
from engine.tools.base import READ_ONLY, BaseTool, Effect, ToolResult

T = "11111111-1111-1111-1111-111111111111"
AGENT = "22222222-2222-2222-2222-222222222222"
AT = "55555555-5555-5555-5555-555555555555"
G = "66666666-6666-6666-6666-666666666666"

pytestmark = pytest.mark.asyncio


class Valve(BaseTool):
    name = "valve"
    description = "Set a valve"
    effect = Effect(kind="control", label="Set a valve", target_param="valve")
    input_schema = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def effect_for(cls, arguments: dict[str, Any]) -> Effect | None:
        return READ_ONLY if arguments.get("operation") == "read" else cls.effect

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content=json.dumps({"ok": True}))


class MemoryStore(BaseTool):
    # no declared effect, still changes state
    name = "memory_store"
    description = "Remember"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content="stored")


class Ledger:
    def __init__(self) -> None:
        self.ops: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, op: str, data: dict[str, Any]) -> None:
        self.ops.append((op, dict(data)))


def _grant(level: int) -> dict[str, Any]:
    return {
        "id": G,
        "tenant_id": T,
        "agent_id": AGENT,
        "action_type_id": AT,
        "scope": None,
        "level": level,
        "ceiling": 4,
        "state": "active",
        "agent_config_hash": None,
        "granted_by": None,
        "creator_id": None,
        "agent_name": "Valve bot",
    }


def _type() -> dict[str, Any]:
    return {
        "id": AT,
        "tenant_id": T,
        "key": "valve.set",
        "label": "Set a valve",
        "tool_name": "valve",
        "match": None,
        "world_model": {"kind": "none"},
        "outcome_probe": None,
        "limits_decision_key": None,
        "max_band_width": None,
        "reversible": True,
        "ceiling": None,
        "policy": None,
    }


@pytest.fixture(autouse=True)
def _clean():
    governance.load_for_test()
    yield
    autonomy.configure()
    autonomy.load_for_test()
    autonomy._loaded_at = 0.0
    governance.configure()
    governance.load_for_test()
    governance.invalidate()


def _setup(level: int | None) -> Ledger:
    ledger = Ledger()
    autonomy.configure(writer=ledger)
    if level is None:
        autonomy.load_for_test([], [], {})
    else:
        autonomy.load_for_test([_type()], [_grant(level)], {})
    return ledger


async def _call(tool: BaseTool, args: dict[str, Any], *, replay: bool, tenant=T):
    root = governance.RunContext(tenant_id=tenant, agent_id=AGENT, replay=replay)
    token = governance.begin_run(root)
    try:
        # the executor nests its own run context under the proof's
        child = governance.RunContext(
            tenant_id=tenant, agent_id=AGENT, parent=governance.current()
        )
        inner = governance.begin_run(child)
        try:
            result = await tool.execute(args)
        finally:
            governance.end_run(inner)
    finally:
        governance.end_run(token)
    await autonomy.flush()
    return result, root


@pytest.mark.parametrize("level", [None, 1, 2, 3, 4])
async def test_effect_never_runs_in_a_replay_at_any_level(level):
    ledger = _setup(level)
    tool = Valve()
    result, root = await _call(tool, {"valve": "V1", "position": 3}, replay=True)
    assert tool.calls == []
    assert not result.is_error
    assert "proof replay" in result.content
    assert result.metadata["autonomy"]["mode"] == "replay"
    assert root.replay_held == [
        {
            "tool": "valve",
            "kind": "control",
            "arguments": {"valve": "V1", "position": 3},
        }
    ]
    # nothing reaches the action ledger, proofs never count toward a track record
    assert ledger.ops == []


async def test_read_tools_run_for_real_in_a_replay():
    _setup(4)
    tool = Valve()
    _, root = await _call(tool, {"operation": "read"}, replay=True)
    assert tool.calls == [{"operation": "read"}]
    assert root.replay_held == []


async def test_stateful_tool_without_an_effect_is_held():
    _setup(None)
    tool = MemoryStore()
    result, root = await _call(tool, {"key": "k", "value": "v"}, replay=True)
    assert tool.calls == []
    assert root.replay_held[0]["tool"] == "memory_store"
    assert root.replay_held[0]["kind"] == "state"


async def test_replay_holds_even_without_a_tenant():
    _setup(None)
    tool = Valve()
    _, root = await _call(tool, {"valve": "V2"}, replay=True, tenant="")
    assert tool.calls == [] and len(root.replay_held) == 1


async def test_outside_a_replay_the_grant_applies_as_before():
    _setup(4)
    tool = Valve()
    result, root = await _call(tool, {"valve": "V1"}, replay=False)
    assert tool.calls == [{"valve": "V1"}]
    assert root.replay_held == []


async def test_replay_root_finds_the_flag_through_the_chain():
    root = governance.RunContext(tenant_id=T, replay=True)
    mid = governance.RunContext(tenant_id=T, parent=root)
    leaf = governance.RunContext(tenant_id=T, parent=mid)
    assert governance.replay_root(leaf) is root
    assert governance.replay_root(governance.RunContext(tenant_id=T)) is None
    assert governance.replay_root(None) is None


async def test_improvements_is_a_kill_switch_scope():
    assert "improvements" in governance.SCOPES
    governance.load_for_test(switches=[(T, "improvements", "*", "too costly")])
    assert governance.stopped(T, "improvements") == (
        "improvements",
        "*",
        "too costly",
    )
