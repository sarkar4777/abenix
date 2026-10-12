"""Per-workspace telemetry limits: platform defaults with an optional per-workspace override."""

from __future__ import annotations

from typing import Any

FIELDS = {
    "max_connections": "telemetry.quota.max_connections",
    "max_devices": "telemetry.quota.max_devices",
    "max_msgs_per_sec": "telemetry.quota.max_msgs_per_sec",
    "retention_days": "telemetry.retention_days",
}
FALLBACK = {
    "max_connections": 20,
    "max_devices": 5000,
    "max_msgs_per_sec": 20000,
    "retention_days": 7,
}
OVERRIDE_KEY = "telemetry_quota"


async def defaults() -> dict[str, int]:
    from app.core.platform_settings import get_int_setting

    return {k: await get_int_setting(key, FALLBACK[k]) for k, key in FIELDS.items()}


def merge(
    base: dict[str, int], tenant_settings: dict[str, Any] | None
) -> dict[str, int]:
    """The workspace override wins where it names a positive whole number."""
    out = dict(base)
    over = (tenant_settings or {}).get(OVERRIDE_KEY) or {}
    if isinstance(over, dict):
        for k in FIELDS:
            try:
                v = int(over.get(k))
            except (TypeError, ValueError):
                continue
            if v > 0:
                out[k] = v
    return out


async def for_tenant(db: Any, tenant_id: Any) -> dict[str, int]:
    from sqlalchemy import select

    from models.tenant import Tenant

    settings = (
        await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar()
    return merge(await defaults(), settings)


def throttle_words(kind: str, limit: int) -> str:
    if kind == "devices":
        return (
            f"This workspace reached its limit of {limit} machines and devices, "
            "so new ones are not added. Forget devices offline for more than an hour on the Devices tab, "
            "or an admin can raise the limit under Admin, Settings, Telemetry."
        )
    return (
        f"This workspace sent more than {limit} telemetry messages a second, "
        "so some readings were skipped. An admin can raise the limit under Admin, Settings, Telemetry."
    )
