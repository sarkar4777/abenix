from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import notifications as notif
from app.core.deps import get_current_user, get_db
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


@router.get("")
async def list_alerts(user: User = Depends(get_current_user)):
    """Current alerts, from Alertmanager when reachable, else Prometheus.

    Admin-only, alert labels can carry tenant identifiers. `source` says
    which backend answered so the page can show it.
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

    return success(
        {
            "alerts": alerts,
            "counts": counts,
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


async def _recently_notified(
    db: AsyncSession, *, fingerprint: str | None, name: str, status: str, cutoff
) -> bool:
    """DB-backed dedupe, holds across API replicas and restarts."""
    from sqlalchemy import select

    from models.notification import Notification

    stmt = select(Notification.id).where(
        Notification.type == "system_alert",
        Notification.metadata_["status"].astext == status,
        Notification.created_at > cutoff,
    )
    if fingerprint:
        stmt = stmt.where(Notification.metadata_["fingerprint"].astext == fingerprint)
    else:
        stmt = stmt.where(Notification.metadata_["alertname"].astext == name)
    r = await db.execute(stmt.limit(1))
    return r.first() is not None


@router.post("/webhook")
async def alert_webhook(
    payload: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Alertmanager v4 webhook. Fans each alert out to admins + Slack."""
    _check_webhook_token(request)
    alerts = payload.get("alerts") or []
    if not isinstance(alerts, list):
        raise HTTPException(status_code=400, detail="alerts must be a list")

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_dedupe_minutes())
    notified = 0
    skipped = 0
    for raw in alerts:
        labels = raw.get("labels") or {}
        annotations = raw.get("annotations") or {}
        name = labels.get("alertname") or "unknown"
        status = (raw.get("status") or "firing").lower()
        if status not in ("firing", "resolved"):
            skipped += 1
            continue
        fingerprint = raw.get("fingerprint") or None
        if await _recently_notified(
            db, fingerprint=fingerprint, name=name, status=status, cutoff=cutoff
        ):
            skipped += 1
            continue
        since = raw.get("startsAt")
        if status == "resolved":
            since = raw.get("endsAt") or since
        try:
            notified += await notif.notify_platform_alert(
                db,
                name=name,
                severity=labels.get("severity") or "info",
                summary=annotations.get("summary")
                or annotations.get("description")
                or "",
                since=since,
                labels=labels,
                fingerprint=fingerprint,
                status=status,
                source="alertmanager",
            )
        except Exception as exc:
            logger.warning("alert webhook notify failed for %s: %s", name, exc)
    await db.commit()
    return success({"received": len(alerts), "notified": notified, "skipped": skipped})
