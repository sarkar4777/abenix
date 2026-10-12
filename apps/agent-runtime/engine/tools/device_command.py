"""device_command: an agent sets a signal on an asset, governed by the policy on its tool settings.

The policy (which assets and signals, when a person approves, how many a minute) is read
by the API from the agent's saved configuration, never from the call. A command that
needs a person goes to /approvals with the asset, the value, the agent's reason and the
recent history, and is sent only once it is approved. When the agent holds an Earned
Autonomy grant for device_command, the grant's level decides instead.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from engine.tools import _telemetry_api as api
from engine.tools.base import BaseTool, ConfigField, Effect, ToolResult

POLL_S = 2.0
EFFECT = Effect(
    kind="control",
    label="Send a command to an asset",
    target_param="asset",
    magnitude_param="value",
    reversible=True,
)


def _int(v: Any, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _signer(a: dict[str, Any], decision: str) -> dict[str, Any]:
    for s in reversed(a.get("signoffs") or []):
        if isinstance(s, dict) and s.get("decision") == decision:
            return s
    return {}


async def _progress(execution_id: str, meta: dict[str, Any]) -> None:
    if not execution_id:
        return
    try:
        from engine import progress

        await progress.publish(
            execution_id,
            {"phase": "autonomy_waiting", "tool": "device_command", "autonomy": meta},
        )
    except Exception:  # noqa: BLE001
        pass


def _status(data: dict[str, Any]) -> None:
    """A live tool_status event on the chat stream, a no-op outside one."""
    try:
        from engine import autonomy

        autonomy.emit("tool_status", data)
    except Exception:  # noqa: BLE001
        pass


def wake_channel(approval_id: str) -> str:
    # the API publishes here the moment a person decides
    return f"approval:{approval_id}:resolved"


async def _decision(approval_id: str) -> dict[str, Any] | None:
    status, data, _ = await api.call("GET", f"/api/approvals/{approval_id}", timeout=10)
    if status == 200 and (data or {}).get("status", "pending") != "pending":
        return data
    return None


async def wait_for(
    approval_id: str, expires_s: int, execution_id: str
) -> dict[str, Any]:
    """Wake the moment a person decides, through Redis, and poll as a fallback.

    A fresh token each read, so a long wait still works.
    """
    import os

    from engine.tools.approval_gate import _clear_waiting, _mark_waiting

    deadline = time.monotonic() + expires_s + 5
    await _mark_waiting(execution_id or None, expires_s + 5)
    r = ps = None
    try:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
            ps = r.pubsub()
            await ps.subscribe(wake_channel(approval_id))
        except Exception:  # noqa: BLE001
            ps = None
        # decided before we listened, or while we subscribed
        got = await _decision(approval_id)
        if got is not None:
            return got
        while time.monotonic() < deadline:
            woke = False
            if ps is not None:
                try:
                    msg = await ps.get_message(
                        ignore_subscribe_messages=True, timeout=POLL_S
                    )
                    woke = bool(msg)
                    # approved goes straight to the send, which checks the approval itself
                    if woke and str(msg.get("data")) == "approved":
                        return {"id": approval_id, "status": "approved", "signoffs": []}
                except Exception:  # noqa: BLE001
                    ps = None
            if ps is None:
                await asyncio.sleep(POLL_S)
            got = await _decision(approval_id)
            if got is not None:
                return got
            if woke:
                # told it was decided but the read lagged, look again shortly
                await asyncio.sleep(0.05)
    finally:
        if ps is not None:
            try:
                await ps.aclose()
            except Exception:  # noqa: BLE001
                pass
        if r is not None:
            try:
                await r.aclose()
            except Exception:  # noqa: BLE001
                pass
        await _clear_waiting(execution_id or None)
    return {"id": approval_id, "status": "expired", "signoffs": []}


class DeviceCommandTool(BaseTool):
    name = "device_command"
    # tells the chat it is waiting for an approval while the call is open
    streams_status = True
    risk_tier = "medium"
    effect = EFFECT
    description = (
        "Set a signal on an asset, such as Mode/Set to safe on an excavator or a meter's setpoint. "
        "Give the asset (key or display name from asset_search), the part when the signal is on "
        "one, the signal, the value and your reason in a sentence. The agent's owner decides which "
        "assets and signals it may command and whether a person approves first. When approval is "
        "needed the call waits for it and says who decided. Returns whether it was published, "
        "whether the asset confirmed the new value, and the timings. Read device_state first so "
        "the reason cites what you saw."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "asset": {
                "type": "string",
                "description": "The asset by key, like groundwork/ipc-ex1 or testbed/meter-1/plc, or its display name.",
            },
            "part": {
                "type": "string",
                "description": "The part (device) the signal is on, like safety. Leave out when the key names it or the signal is on the asset itself.",
            },
            "signal": {
                "type": "string",
                "description": "The signal to set, like Mode/Set or Setpoint.",
            },
            "value": {
                "description": "The value to set: true, false, a number or text such as safe.",
            },
            "reason": {
                "type": "string",
                "description": "Why, in one sentence a person can check, citing the readings, like 'Pump 1 pressure rose from 260 to 318 bar in 10 minutes'.",
            },
        },
        "required": ["asset", "signal", "value", "reason"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "published": {"type": "boolean"},
            "confirmed": {"type": ["boolean", "null"]},
            "approved_by": {"type": ["string", "null"]},
            "timings": {"type": "object"},
        },
    }
    config_fields = (
        ConfigField(
            key="TELEMETRY_COMMAND_APPROVAL_WAIT_S",
            label="Longest wait for an approval (seconds)",
            kind="int",
            required=False,
            group="Telemetry",
            description="A command nobody approves in this time is not sent. The approval itself expires after 30 minutes.",
            default="1800",
        ),
    )

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id or ""

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        info = api.run_info()
        if not info["agent_id"]:
            return ToolResult(
                content="device_command only runs inside an agent's run, where its command policy applies.",
                is_error=True,
            )
        body = {
            "agent_id": info["agent_id"],
            "execution_id": info["execution_id"] or None,
            "asset": str(arguments.get("asset") or "").strip() or None,
            "part": (
                str(arguments["part"]).strip()
                if arguments.get("part") not in (None, "")
                else None
            ),
            "signal": str(arguments.get("signal") or "").strip(),
            "value": arguments.get("value"),
            "reason": str(arguments.get("reason") or "").strip(),
            "read": api.reads_of(info["execution_id"])[:10],
        }
        if not body["asset"] or not body["signal"]:
            return ToolResult(
                content="Name the asset and the signal to set.", is_error=True
            )
        status, data, err = await api.call(
            "POST", "/api/telemetry/loop/commands/propose", body=body
        )
        if status == 0 or status >= 300:
            return ToolResult(
                content=err,
                is_error=True,
                metadata={"status": status, "refused": data},
            )
        prop = data or {}
        if prop.get("test"):
            return ToolResult(
                content=json.dumps(
                    {
                        "published": False,
                        "test": True,
                        "message": prop.get("message"),
                        "target": prop.get("target"),
                        "preview": prop.get("preview"),
                    },
                    default=str,
                ),
                metadata={"test": True},
            )
        approval = prop.get("approval") or {}
        approval_wait_ms = None
        if prop.get("needs_approval"):
            aid = approval.get("id")
            if not aid:
                return ToolResult(
                    content="Not sent. The command needs approval and none could be created.",
                    is_error=True,
                )
            await _progress(
                info["execution_id"],
                {
                    "status": "pending",
                    "approval_id": aid,
                    "action_label": f"Set {body['signal']} on {(prop.get('target') or {}).get('name')}",
                    "link": approval.get("link"),
                },
            )
            _status(
                {
                    "name": "device_command",
                    "status": "waiting_approval",
                    "approval_id": aid,
                    "message": "Waiting for approval. Open Approvals to approve or deny it.",
                    "link": approval.get("link"),
                }
            )
            limit = _int(self.cfg("TELEMETRY_COMMAND_APPROVAL_WAIT_S"), 1800)
            limit = max(10, min(limit, int(approval.get("expires_seconds") or 1800)))
            w0 = time.time()
            final = await wait_for(aid, limit, info["execution_id"])
            approval_wait_ms = int((time.time() - w0) * 1000)
            st = final.get("status") or "expired"
            _status({"name": "device_command", "status": st, "approval_id": aid})
            if st != "approved":
                who = _signer(final, "deny") or _signer(final, "return")
                name = who.get("user_name") or "A reviewer"
                why = (who.get("reason") or "").strip().rstrip(".")
                if st in ("denied", "returned"):
                    text = f"Not sent. {name} denied the command" + (
                        f": {why}." if why else "."
                    )
                else:
                    text = f"Not sent. Nobody approved the command in time, the approval is {st}."
                return ToolResult(
                    content=text + " Do not tell the user it was done.",
                    is_error=True,
                    metadata={
                        "approval_id": aid,
                        "decision": st,
                        "status": (
                            "denied" if st in ("denied", "returned") else "expired"
                        ),
                        "reason": why or None,
                        "decided_by": who.get("user_name"),
                    },
                )
            body["approval_id"] = aid
        target = prop.get("target") or {}
        if target.get("group") and target.get("node"):
            body.update(
                {
                    "asset": None,
                    "group": target["group"],
                    "node": target["node"],
                    "part": target.get("device") or "",
                }
            )
        status, sent, err = await api.call(
            "POST", "/api/telemetry/loop/commands/send", body=body, timeout=30
        )
        if status == 0 or status >= 300:
            return ToolResult(
                content=err,
                is_error=True,
                metadata={"status": status, "refused": sent},
            )
        sent = sent or {}
        timings = dict(sent.get("timings") or {})
        timings["approval_wait_ms"] = approval_wait_ms
        timings["total_ms"] = int((time.time() - t0) * 1000)
        out = {
            "published": sent.get("published"),
            "confirmed": sent.get("confirmed"),
            "already_at_value": bool(sent.get("already_at_value")),
            "confirm_note": sent.get("confirm_note"),
            "target": sent.get("target"),
            "command": sent.get("command"),
            "approved_by": sent.get("approved_by"),
            "approval_id": sent.get("approval_id"),
            "governed_by": prop.get("governed_by"),
            "at": sent.get("at"),
            "timings": timings,
        }
        return ToolResult(
            content=json.dumps(out, default=str),
            metadata={
                "published": bool(out["published"]),
                "confirmed": out["confirmed"],
                "approval_id": out["approval_id"],
            },
        )
