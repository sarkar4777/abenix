from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.core.responses import success
from models.user import User

router = APIRouter(prefix="/api/admin/alerts", tags=["admin-alerts"])

# In-cluster service. Overridable for local dev / docker-compose.
_PROM_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://abenix-prometheus.abenix.svc.cluster.local:9090",
)


class PrometheusUnavailable(Exception):
    """Raised when Prometheus cannot be reached or answers with an error."""


def _shape_alert(raw: dict[str, Any]) -> dict[str, Any]:
    """Trim the upstream payload to the fields the /alerts page renders."""
    labels = raw.get("labels") or {}
    annotations = raw.get("annotations") or {}
    return {
        "name": labels.get("alertname") or raw.get("name") or "unknown",
        "state": raw.get("state") or "inactive",
        "severity": labels.get("severity") or "info",
        "active_since": raw.get("activeAt"),
        "value": raw.get("value"),
        "summary": annotations.get("summary"),
        "description": annotations.get("description"),
        "runbook": annotations.get("runbook"),
        "labels": labels,
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
    """Shaped alerts from Prometheus /api/v1/alerts. Shared with the scheduler poller."""
    data = await _prom_get("/api/v1/alerts")
    return [_shape_alert(a) for a in (data.get("alerts") or [])]


def _require_admin(user: User) -> None:
    if not (getattr(user, "is_admin", False) or user.role == "admin"):
        raise HTTPException(status_code=403, detail="admin-only")


@router.get("")
async def list_alerts(user: User = Depends(get_current_user)):
    """Proxy Prometheus /api/v1/alerts and return a clean shape.

    Returns the current alerting state (firing / pending / inactive)
    plus a summary count. Admin-only — alert metadata can leak tenant
    identifiers via labels.
    """
    _require_admin(user)
    try:
        alerts = await fetch_prometheus_alerts()
    except PrometheusUnavailable as exc:
        # Surface as 502 — the API itself is fine, the upstream isn't.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    counts = {"firing": 0, "pending": 0, "inactive": 0}
    for a in alerts:
        s = a["state"]
        counts[s] = counts.get(s, 0) + 1

    return success(
        {
            "alerts": alerts,
            "counts": counts,
            "prometheus_url": _PROM_URL,
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
