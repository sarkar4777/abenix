"""Run-time governance: tenant risk policies, kill switches and the tier a run has reached.

Checks are synchronous reads of an in-memory snapshot refreshed every few
seconds, the same pattern as engine.credentials, so a tool call never waits
on the database.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from engine import risk

logger = logging.getLogger(__name__)

SCOPES = (
    "all",
    "agent",
    "pipeline",
    "tool",
    "model",
    "trigger",
    "decision",
    "source",
    "improvements",
)

_ttl = 5.0
_policies: dict[tuple[str, str], dict[str, Any]] = {}
# (tenant or "", scope, target) -> reason
_switches: dict[tuple[str, str, str], str] = {}
# agents and pipelines above low, by id
_agent_tiers: dict[str, str] = {}
_loaded_at = 0.0
_lock: asyncio.Lock | None = None
_bg: asyncio.Task | None = None
_loader: Callable[[], Awaitable[tuple | None]] | None = None
_warned = False


class Stopped(Exception):
    """A kill switch covers what was about to run."""

    def __init__(self, scope: str, target: str, reason: str) -> None:
        super().__init__(f"{scope} {target} is stopped: {reason}")
        self.scope = scope
        self.target = target
        self.reason = reason

    def message(self) -> str:
        what = (
            "Everything" if self.scope == "all" else f"The {self.scope} {self.target}"
        )
        why = f" Reason given: {self.reason.rstrip('. ')}." if self.reason else ""
        return f"{what} is stopped by a kill switch.{why} An admin can resume it under Admin, Risk and Controls."


@dataclass
class RunContext:
    tenant_id: str
    execution_id: str = ""
    agent_name: str = ""
    base_tier: str = "low"
    tier: str = "low"
    reasons: list[dict[str, Any]] = field(default_factory=list)
    # what a kill switch would name to stop this run: agent or pipeline, and its id
    scope: str = "agent"
    subject_id: str = ""
    parent: "RunContext | None" = None
    # who the run acts for, read by the autonomy gate
    agent_id: str = ""
    user_id: str = ""
    agent_config_hash: str = ""
    # a proof replay: every effect tool is recorded, never run
    replay: bool = False
    replay_held: list[dict[str, Any]] = field(default_factory=list)

    def chain(self) -> list["RunContext"]:
        out, node = [], self
        while node is not None:
            out.append(node)
            node = node.parent
        return out

    def raise_to(self, tier: str, source: str, detail: str = "") -> None:
        if risk.above(tier, self.tier):
            self.tier = risk.normalize(tier)
            self.reasons.append({"tier": self.tier, "source": source, "detail": detail})


_run: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "abenix_governance_run", default=None
)
# true while a governed tool call is in progress, so nested wrappers check once
_in_tool: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "abenix_governance_in_tool", default=False
)


def configure(
    *,
    loader: Callable[[], Awaitable[tuple | None]] | None = None,
    ttl: float | None = None,
) -> None:
    global _loader, _ttl, _lock
    _loader = loader
    if ttl is not None:
        _ttl = float(ttl)
    _lock = None
    invalidate()


def invalidate() -> None:
    global _loaded_at
    _loaded_at = 0.0


async def _read_db() -> tuple | None:
    global _warned
    if _loader is not None:
        return await _loader()
    from engine.credentials import _db_url

    url, ssl = _db_url()
    if not url:
        if not _warned:
            logger.warning(
                "DATABASE_URL is not set, governance uses the default risk policies and no kill switches"
            )
            _warned = True
        return None
    import asyncpg

    kwargs: dict[str, Any] = {"timeout": 2}
    if ssl:
        kwargs["ssl"] = "require" if ssl in ("true", "1", "require") else ssl
    conn = await asyncpg.connect(url, **kwargs)
    try:
        try:
            pol = await conn.fetch("SELECT tenant_id, tier, policy FROM risk_policies")
            sw = await conn.fetch(
                "SELECT tenant_id, scope, target, reason FROM kill_switches WHERE active"
            )
            ag = await conn.fetch(
                "SELECT id, model_config->>'risk_tier' AS tier FROM agents "
                "WHERE model_config->>'risk_tier' IN ('medium', 'high', 'critical')"
            )
        except Exception as exc:  # noqa: BLE001
            if "does not exist" in str(exc):
                return [], [], []
            raise
    finally:
        await conn.close()
    return (
        [(r["tenant_id"], r["tier"], r["policy"]) for r in pol],
        [(r["tenant_id"], r["scope"], r["target"], r["reason"]) for r in sw],
        [(r["id"], r["tier"]) for r in ag],
    )


def _load(pol: list, sw: list, agents: list | None = None) -> None:
    global _policies, _switches, _agent_tiers
    import json

    policies: dict[tuple[str, str], dict[str, Any]] = {}
    for tenant, tier, p in pol:
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except ValueError:
                p = {}
        policies[(str(tenant), risk.normalize(tier))] = p or {}
    switches: dict[tuple[str, str, str], str] = {}
    for tenant, scope, target, reason in sw:
        switches[(str(tenant or ""), str(scope), str(target or "*"))] = reason or ""
    _policies, _switches = policies, switches
    _agent_tiers = {str(a): risk.normalize(t) for a, t in (agents or [])}


async def _refresh(force: bool) -> None:
    global _loaded_at
    async with _lock:  # type: ignore[union-attr]
        if not force and time.monotonic() - _loaded_at < _ttl:
            return
        try:
            data = await _read_db()
        except Exception as exc:  # noqa: BLE001
            logger.debug("governance refresh failed: %s", exc)
            data = None
        if data is not None:
            _load(*data)
        _loaded_at = time.monotonic()


async def ensure_fresh(force: bool = False) -> None:
    """Serve the snapshot and refresh it behind the caller. Only a first load or an invalidate waits."""
    global _lock, _bg
    if not force and time.monotonic() - _loaded_at < _ttl:
        return
    if _lock is None:
        _lock = asyncio.Lock()
    if not force and _loaded_at:
        if not _lock.locked() and (_bg is None or _bg.done()):
            _bg = asyncio.create_task(_refresh(False))
        return
    await _refresh(force)


def load_for_test(
    policies: list | None = None,
    switches: list | None = None,
    agents: list | None = None,
) -> None:
    """Replace the snapshot directly, for tests."""
    global _loaded_at
    _load(policies or [], switches or [], agents or [])
    _loaded_at = time.monotonic() + 3600


def policy(tenant_id: Any, tier: str) -> dict[str, Any]:
    return risk.merged_policy(
        tier, _policies.get((str(tenant_id or ""), risk.normalize(tier)))
    )


def agent_tier(agent_id: Any) -> str:
    return _agent_tiers.get(str(agent_id or ""), "low")


def stopped(
    tenant_id: Any, scope: str, target: str = "*"
) -> tuple[str, str, str] | None:
    """The switch that stops this, or None. Platform switches have no tenant."""
    tenant = str(tenant_id or "")
    target = str(target or "*")
    for t in (tenant, ""):
        for key in ((t, "all", "*"), (t, scope, "*"), (t, scope, target)):
            if key in _switches:
                return key[1], key[2], _switches[key]
    return None


def check(tenant_id: Any, scope: str, target: str = "*") -> None:
    hit = stopped(tenant_id, scope, target)
    if hit:
        raise Stopped(hit[0], target if hit[1] == "*" else hit[1], hit[2])


def begin_run(ctx: RunContext) -> tuple[contextvars.Token, contextvars.Token]:
    ctx.tier = risk.highest([ctx.tier, ctx.base_tier])
    # an agent started from inside a tool, such as agent_step, governs its own tools
    return _run.set(ctx), _in_tool.set(False)


def end_run(token: tuple[contextvars.Token, contextvars.Token]) -> None:
    run_token, tool_token = token
    try:
        _in_tool.reset(tool_token)
        _run.reset(run_token)
    except ValueError:
        _in_tool.set(False)
        _run.set(None)


def current() -> RunContext | None:
    return _run.get()


def replay_root(run: RunContext | None) -> RunContext | None:
    """The proof replay this run belongs to, nested runs included."""
    for ctx in run.chain() if run is not None else ():
        if ctx.replay:
            return ctx
    return None


def in_tool() -> bool:
    return _in_tool.get()


def enter_tool() -> contextvars.Token:
    return _in_tool.set(True)


def exit_tool(token: contextvars.Token) -> None:
    _in_tool.reset(token)
