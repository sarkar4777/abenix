"""Calls from the telemetry tools to the API, as the person the run acts for.

Each call mints a fresh short-lived token, so a call made after a long wait for an
approval still authenticates. Asset names resolve through the API so the run sees
only what that person's teams may see.
"""

from __future__ import annotations

import os
from typing import Any

from engine import credentials, governance

API_TIMEOUT = 20.0
ASSET_PROPS: dict[str, Any] = {
    "asset": {
        "type": "string",
        "description": "One asset by its key from asset_search, like groundwork/ipc-ex1 or groundwork/ipc-ex1/engine, or by its display name, like Excavator EX1.",
    },
    "assets": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Several assets by key or display name, up to 50, for example every haul truck asset_search found.",
    },
    "where": {
        "type": "object",
        "description": "Every asset matching these, instead of naming them: type (vehicle, machine, sensor, device, system), tag, group, or q (a search on names).",
        "properties": {
            "type": {"type": "string"},
            "tag": {"type": "string"},
            "group": {"type": "string"},
            "q": {"type": "string"},
        },
    },
}
MAX_ASSETS = 50
READS_PER_RUN = 20
RUNS_KEPT = 500
# per run, the signals the agent read, so an approver sees what it looked at
_reads: dict[str, list[dict[str, str]]] = {}


def note_read(group: str, node: str, device: str | None, signals: list[str]) -> None:
    run = run_info()["execution_id"]
    if not run:
        return
    got = _reads.setdefault(run, [])
    for s in signals:
        s = str(s or "").strip()
        # a prefix like Engine/ or Engine* is a filter, not a signal
        if not s or s.endswith("/") or s.endswith("*"):
            continue
        row = {"group": group, "node": node, "device": device or "", "signal": s}
        if row not in got and len(got) < READS_PER_RUN:
            got.append(row)
    while len(_reads) > RUNS_KEPT:
        _reads.pop(next(iter(_reads)))


def reads_of(execution_id: str) -> list[dict[str, str]]:
    return list(_reads.get(execution_id or "", []))


def run_info() -> dict[str, str]:
    run = governance.current()
    tenant = (
        str(run.tenant_id)
        if run is not None and run.tenant_id
        else credentials.current_tenant() or os.environ.get("TENANT_ID", "").strip()
    )
    return {
        "tenant": tenant,
        "user_id": str(getattr(run, "user_id", "") or "") if run else "",
        "agent_id": str(getattr(run, "agent_id", "") or "") if run else "",
        "execution_id": str(getattr(run, "execution_id", "") or "") if run else "",
        "agent_name": str(getattr(run, "agent_name", "") or "") if run else "",
    }


def headers() -> dict[str, str]:
    from engine.tools import approval_gate as ag

    info = run_info()
    return ag.auth_headers(ag.run_token(info["user_id"], info["tenant"]))


def base_url() -> str:
    from engine.tools import approval_gate as ag

    return ag._api_base_url()


async def call(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = API_TIMEOUT,
) -> tuple[int, Any, str]:
    """(status, data, plain error). Status 0 means the API could not be reached."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.request(
                method,
                f"{base_url()}{path}",
                params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                json=body,
                headers=headers(),
            )
    except httpx.HTTPError as exc:
        return 0, None, f"The telemetry API could not be reached: {exc}"
    try:
        doc = r.json()
    except ValueError:
        doc = {}
    if r.status_code >= 300:
        err = (doc or {}).get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else None
        if not msg:
            detail = (doc or {}).get("detail")
            msg = detail if isinstance(detail, str) else f"HTTP {r.status_code}"
        return r.status_code, (doc or {}).get("error"), str(msg)
    return r.status_code, (doc or {}).get("data"), ""


def wants_assets(args: dict[str, Any]) -> bool:
    return bool(args.get("asset") or args.get("assets") or args.get("where"))


async def resolve(args: dict[str, Any]) -> tuple[list[dict[str, Any]], str, dict]:
    """The assets the call names, a plain problem when there is one, and what could not be matched."""
    refs: list[str] = []
    if args.get("asset"):
        refs.append(str(args["asset"]))
    many = args.get("assets") or []
    if isinstance(many, str):
        many = [x.strip() for x in many.split(",") if x.strip()]
    refs.extend(str(x) for x in many)
    where = args.get("where") if isinstance(args.get("where"), dict) else {}
    body: dict[str, Any] = {"refs": refs[: MAX_ASSETS * 2], "limit": MAX_ASSETS}
    if not refs:
        body.update({k: str(where.get(k) or "") for k in ("type", "tag", "group", "q")})
    status, data, err = await call("POST", "/api/telemetry/loop/resolve", body=body)
    if status == 0 or status >= 300:
        return [], err, {}
    data = data or {}
    found = data.get("assets") or []
    extra = {
        "unknown": data.get("unknown") or [],
        "ambiguous": data.get("ambiguous") or {},
        "truncated": bool(data.get("truncated")),
        "total": data.get("total"),
    }
    if not found:
        bits = []
        if extra["unknown"]:
            bits.append(f"no asset called {', '.join(extra['unknown'][:5])}")
        for name, keys in list(extra["ambiguous"].items())[:3]:
            bits.append(f"{name} could be {', '.join(keys[:5])}")
        why = "; ".join(bits) or "nothing matched"
        return (
            [],
            f"No assets to read: {why}. Use asset_search to find the keys, then pass them as asset or assets.",
            extra,
        )
    return found, "", extra
