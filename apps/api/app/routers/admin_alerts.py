from __future__ import annotations

import hmac
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core import notifications as notif
from app.core.deps import get_current_user
from app.core.responses import success
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/alerts", tags=["admin-alerts"])

# In-cluster service. Overridable for local dev / docker-compose.
_PROM_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://abenix-prometheus.abenix.svc.cluster.local:9090",
)

# The scheduler's poll_platform_alerts job is gone, Alertmanager pushes here instead.


class PrometheusUnavailable(Exception):
    """Raised when Prometheus cannot be reached or answers with an error."""


class AlertmanagerUnavailable(Exception):
    """Raised when Alertmanager is not configured, unreachable or errors."""


def _alertmanager_url() -> str:
    return (os.environ.get("ALERTMANAGER_URL") or "").strip().rstrip("/")


def _webhook_token() -> str:
    return (os.environ.get("ALERT_WEBHOOK_TOKEN") or "").strip()


def _dedupe_minutes() -> int:
    try:
        return int(os.environ.get("PLATFORM_ALERT_DEDUPE_MINUTES", "30"))
    except ValueError:
        return 30


def _shape_alert(raw: dict[str, Any]) -> dict[str, Any]:
    """Trim the Prometheus payload to the fields the /alerts page renders."""
    labels = raw.get("labels") or {}
    annotations = raw.get("annotations") or {}
    return {
        "name": labels.get("alertname") or raw.get("name") or "unknown",
        "state": raw.get("state") or "inactive",
        "severity": labels.get("severity") or "info",
        "active_since": raw.get("activeAt"),
        "ends_at": None,
        "value": raw.get("value"),
        "summary": annotations.get("summary"),
        "description": annotations.get("description"),
        "runbook": annotations.get("runbook"),
        "labels": labels,
        "fingerprint": None,
        "silenced": False,
        "inhibited": False,
    }


def _shape_am_alert(raw: dict[str, Any]) -> dict[str, Any]:
    """Same shape from an Alertmanager v2 alert, with silence state kept."""
    labels = raw.get("labels") or {}
    annotations = raw.get("annotations") or {}
    status = raw.get("status") or {}
    silenced = bool(status.get("silencedBy"))
    inhibited = bool(status.get("inhibitedBy"))
    am_state = status.get("state") or "active"
    if am_state == "active":
        state = "firing"
    elif silenced:
        state = "silenced"
    elif inhibited:
        state = "inhibited"
    else:
        state = am_state
    ends_at = raw.get("endsAt")
    if ends_at and ends_at.startswith("0001-"):
        ends_at = None
    if state == "firing":
        # Alertmanager keeps pushing endsAt ahead while it fires, it is not a resolve time
        ends_at = None
    return {
        "name": labels.get("alertname") or "unknown",
        "state": state,
        "severity": labels.get("severity") or "info",
        "active_since": raw.get("startsAt"),
        "ends_at": ends_at,
        "value": None,
        "summary": annotations.get("summary"),
        "description": annotations.get("description"),
        "runbook": annotations.get("runbook"),
        "labels": labels,
        "fingerprint": raw.get("fingerprint"),
        "silenced": silenced,
        "inhibited": inhibited,
    }


async def _prom_get(path: str) -> dict[str, Any]:
    upstream = f"{_PROM_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(upstream)
    except httpx.HTTPError as exc:
        raise PrometheusUnavailable(
            f"prometheus unreachable at {upstream}: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise PrometheusUnavailable(f"prometheus returned {resp.status_code}")
    payload = resp.json()
    if payload.get("status") != "success":
        raise PrometheusUnavailable(
            f"prometheus error: {payload.get('error') or payload.get('errorType')}"
        )
    return payload.get("data") or {}


async def fetch_prometheus_alerts() -> list[dict[str, Any]]:
    """Shaped alerts from Prometheus /api/v1/alerts."""
    data = await _prom_get("/api/v1/alerts")
    return [_shape_alert(a) for a in (data.get("alerts") or [])]


async def fetch_alertmanager_alerts() -> list[dict[str, Any]]:
    """Shaped alerts from Alertmanager /api/v2/alerts, silenced ones included."""
    base = _alertmanager_url()
    if not base:
        raise AlertmanagerUnavailable("ALERTMANAGER_URL not set")
    upstream = f"{base}/api/v2/alerts?active=true&silenced=true&inhibited=true"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(upstream)
    except httpx.HTTPError as exc:
        raise AlertmanagerUnavailable(
            f"alertmanager unreachable at {upstream}: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise AlertmanagerUnavailable(f"alertmanager returned {resp.status_code}")
    payload = resp.json()
    if not isinstance(payload, list):
        raise AlertmanagerUnavailable("alertmanager returned a non-list body")
    return [_shape_am_alert(a) for a in payload]


def _require_admin(user: User) -> None:
    if not (getattr(user, "is_admin", False) or user.role == "admin"):
        raise HTTPException(status_code=403, detail="admin-only")


def filter_alerts(
    alerts: list[dict[str, Any]],
    *,
    q: str = "",
    alertname: str = "",
    status: str = "",
    labels: list[str] | None = None,
    rule_id: str = "",
) -> list[dict[str, Any]]:
    """Alerts matching every filter given. label is key:value, q matches name, summary or any label."""
    want: list[tuple[str, str]] = []
    for item in labels or []:
        k, sep, v = item.partition(":")
        if sep and k.strip():
            want.append((k.strip(), v.strip()))
    if rule_id:
        want.append(("rule_id", rule_id.strip()))
    names = {n.strip().lower() for n in alertname.split(",") if n.strip()}
    states = {x.strip().lower() for x in status.split(",") if x.strip()}
    needle = q.strip().lower()
    out = []
    for a in alerts:
        lab = a.get("labels") or {}
        if names and (a.get("name") or "").lower() not in names:
            continue
        if states and (a.get("state") or "").lower() not in states:
            continue
        if any(str(lab.get(k, "")) != v for k, v in want):
            continue
        if needle:
            hay = " ".join(
                [str(a.get("name") or ""), str(a.get("summary") or "")]
                + [f"{k}={v}" for k, v in lab.items()]
            ).lower()
            if needle not in hay:
                continue
        out.append(a)
    return out


@router.get("")
async def list_alerts(
    user: User = Depends(get_current_user),
    q: str = Query("", max_length=200),
    alertname: str = Query("", max_length=200),
    status: str = Query("", max_length=100),
    label: list[str] = Query(default=[]),
    rule_id: str = Query("", max_length=100),
):
    """Current alerts, from Alertmanager when reachable, else Prometheus.

    Admin-only, alert labels can carry tenant identifiers. `source` says
    which backend answered so the page can show it. Filters narrow `alerts`,
    `counts` and `total` stay over everything.
    """
    _require_admin(user)
    source = "alertmanager"
    try:
        alerts = await fetch_alertmanager_alerts()
    except AlertmanagerUnavailable as am_exc:
        if _alertmanager_url():
            logger.warning("alertmanager fallback to prometheus: %s", am_exc)
        source = "prometheus"
        try:
            alerts = await fetch_prometheus_alerts()
        except PrometheusUnavailable as exc:
            # 502, the API itself is fine, both upstreams are not.
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    counts = {"firing": 0, "pending": 0, "inactive": 0}
    for a in alerts:
        s = a["state"]
        counts[s] = counts.get(s, 0) + 1
    total = len(alerts)
    alerts = filter_alerts(
        alerts,
        q=q,
        alertname=alertname,
        status=status,
        labels=label,
        rule_id=rule_id,
    )

    return success(
        {
            "alerts": alerts,
            "counts": counts,
            "total": total,
            "matched": len(alerts),
            "source": source,
            "prometheus_url": _PROM_URL,
            "alertmanager_url": _alertmanager_url(),
        }
    )


@router.get("/rules")
async def list_rules(user: User = Depends(get_current_user)):
    """Proxy Prometheus /api/v1/rules — useful to confirm rules loaded."""
    _require_admin(user)
    try:
        data = await _prom_get("/api/v1/rules")
    except PrometheusUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    groups = data.get("groups") or []
    rule_count = sum(len(g.get("rules") or []) for g in groups)
    return success({"groups": groups, "rule_count": rule_count})


def _check_webhook_token(request: Request) -> None:
    expected = _webhook_token()
    if not expected:
        raise HTTPException(status_code=503, detail="ALERT_WEBHOOK_TOKEN not set")
    headers = request.headers
    presented = (headers.get("x-alert-token") or "").strip()
    if not presented:
        auth = (headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="bad alert webhook token")


# alerts that arrive one per device and are folded into one per source
_GROUPED = {"TelemetryDeviceOffline", "TelemetryDevicesOffline"}


def _max_per_request() -> int:
    try:
        return max(1, int(os.environ.get("ALERT_WEBHOOK_MAX_ALERTS", "200")))
    except ValueError:
        return 200


def _event_key(ev: dict[str, Any]) -> str:
    if ev.get("group_key"):
        return f"grp:{ev['group_key']}"
    if ev.get("fingerprint"):
        return f"fp:{ev['fingerprint']}"
    return f"name:{ev['name']}"


def plan_batch(alerts: list[Any], cap: int) -> tuple[list[dict[str, Any]], int, int]:
    """Turn a webhook body into events, telemetry device alerts grouped per source.

    Returns (events, skipped, dropped). Pure, no I/O.
    """
    events: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    skipped = 0
    for raw in alerts:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        labels = raw.get("labels") or {}
        annotations = raw.get("annotations") or {}
        name = labels.get("alertname") or "unknown"
        status = (raw.get("status") or "firing").lower()
        if status not in ("firing", "resolved"):
            skipped += 1
            continue
        since = raw.get("startsAt")
        if status == "resolved":
            since = raw.get("endsAt") or since
        summary = annotations.get("summary") or annotations.get("description") or ""
        if name in _GROUPED and labels.get("connection"):
            tenant = str(labels.get("tenant_id") or "")
            gk = f"TelemetryDeviceOffline|{tenant}|{labels['connection']}|{status}"
            g = groups.get(gk)
            if g is None:
                g = groups[gk] = {
                    "name": "TelemetryDeviceOffline",
                    "status": status,
                    "severity": labels.get("severity") or "warning",
                    "since": since,
                    "fingerprint": None,
                    "group_key": gk,
                    "labels": {
                        k: labels[k]
                        for k in ("alertname", "severity", "tenant_id", "connection")
                        if labels.get(k)
                    },
                    "summaries": [],
                    "devices": [],
                }
                g["labels"]["alertname"] = "TelemetryDeviceOffline"
                events.append(g)
            what = "/".join(
                str(labels[k])
                for k in ("node", "device")
                if labels.get(k) and labels[k] not in ("-", "*")
            )
            g["devices"].append(what or str(labels.get("device") or "?"))
            g["summaries"].append(summary)
            continue
        events.append(
            {
                "name": name,
                "status": status,
                "severity": labels.get("severity") or "info",
                "since": since,
                "fingerprint": raw.get("fingerprint") or None,
                "group_key": None,
                "labels": labels,
                "summary": summary,
            }
        )
    for g in groups.values():
        devices = g.pop("devices")
        summaries = g.pop("summaries")
        conn = g["labels"].get("connection")
        if len(devices) == 1:
            g["summary"] = summaries[0] or f"A device on {conn} went offline"
        else:
            sample = ", ".join(devices[:5]) + (", and more" if len(devices) > 5 else "")
            if g["status"] == "resolved":
                g["summary"] = (
                    f"Offline alert for {len(devices)} devices on {conn} ({sample})"
                )
            else:
                g["summary"] = (
                    f"{len(devices)} devices on {conn} went offline: {sample}"
                )
        g["labels"]["devices"] = str(len(devices))
    dropped = max(0, len(events) - cap)
    return events[:cap], skipped, dropped


_local_seen: dict[str, float] = {}


async def claim_events(events: list[dict[str, Any]], window_s: int) -> list[bool]:
    """SET NX EX per (event, status), True where this call claims it first."""
    keys = [f"alerts:seen:{ev['status']}:{_event_key(ev)}" for ev in events]
    if not keys:
        return []
    try:
        from app.core.hitl import get_redis

        r = await get_redis()
        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.set(k, "1", nx=True, ex=window_s)
        import asyncio

        res = await asyncio.wait_for(pipe.execute(), timeout=2.0)
        return [bool(x) for x in res]
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert dedupe falls back to this replica: %s", exc)
    import time

    now = time.monotonic()
    if len(_local_seen) > 50_000:
        _local_seen.clear()
    out = []
    for k in keys:
        if _local_seen.get(k, 0.0) > now:
            out.append(False)
        else:
            _local_seen[k] = now + window_s
            out.append(True)
    return out


async def deliver_events(events: list[dict[str, Any]]) -> int:
    """One short transaction on the background pool for the whole batch."""
    from app.core.deps import bg_session

    written = 0
    admins_cache: dict[str, list] = {}
    async with bg_session() as db:
        for ev in events:
            try:
                written += await notif.notify_platform_alert(
                    db,
                    name=ev["name"],
                    severity=ev["severity"],
                    summary=ev["summary"],
                    since=ev["since"],
                    labels=ev["labels"],
                    fingerprint=ev["fingerprint"],
                    status=ev["status"],
                    source="alertmanager",
                    link="/telemetry" if ev.get("group_key") else "/alerts",
                    admins_cache=admins_cache,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("alert notify failed for %s: %s", ev["name"], exc)
        await db.commit()
    return written


_queue: Any = None
_worker: Any = None


def _queue_max() -> int:
    try:
        return max(1, int(os.environ.get("ALERT_WEBHOOK_QUEUE_MAX", "20")))
    except ValueError:
        return 20


async def _drain() -> None:
    while True:
        batch = await _queue.get()
        try:
            await deliver_events(batch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("alert batch delivery failed: %s", exc)
        finally:
            _queue.task_done()


def enqueue(events: list[dict[str, Any]]) -> bool:
    """Hand a batch to the single delivery worker, False when its queue is full."""
    import asyncio

    global _queue, _worker
    if _queue is None:
        _queue = asyncio.Queue(maxsize=_queue_max())
    if _worker is None or _worker.done():
        _worker = asyncio.get_running_loop().create_task(_drain())
    try:
        _queue.put_nowait(events)
        return True
    except asyncio.QueueFull:
        return False


@router.post("/webhook")
async def alert_webhook(payload: dict[str, Any], request: Request):
    """Alertmanager v4 webhook. Dedupes in Redis, answers at once, delivers in the background."""
    _check_webhook_token(request)
    alerts = payload.get("alerts") or []
    if not isinstance(alerts, list):
        raise HTTPException(status_code=400, detail="alerts must be a list")

    events, skipped, dropped = plan_batch(alerts, _max_per_request())
    claimed = await claim_events(events, _dedupe_minutes() * 60)
    fresh = [ev for ev, ok in zip(events, claimed) if ok]
    skipped += len(events) - len(fresh)
    queued = 0
    if fresh:
        if enqueue(fresh):
            queued = len(fresh)
        else:
            dropped += len(fresh)
            logger.warning("alert queue full, %d alerts dropped", len(fresh))
    return success(
        {
            "received": len(alerts),
            "queued": queued,
            "skipped": skipped,
            "dropped": dropped,
        }
    )
