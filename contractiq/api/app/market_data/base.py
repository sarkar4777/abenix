"""Adapter base class. Every concrete adapter is one file under adapters/."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class FetchResult:
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    value: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    series: list[dict[str, Any]] | None = None
    source_slug: str = ""
    instrument_kind: str = "spot"
    unit: str = ""
    error: str | None = None


class MarketDataAdapter:
    """Subclass per source. Adapter handles its own caching window."""

    slug: str = ""
    name: str = ""
    provider: str = ""
    asset_class: str = ""
    instrument_kind: str = "spot"
    default_unit: str = ""
    config_schema: dict[str, Any] = {}

    async def fetch(self, params: dict[str, Any] | None = None) -> FetchResult:
        raise NotImplementedError

    async def health(self) -> dict[str, Any]:
        return {"slug": self.slug, "ok": True}

    def describe(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "provider": self.provider,
            "asset_class": self.asset_class,
            "instrument_kind": self.instrument_kind,
            "default_unit": self.default_unit,
            "config_schema": self.config_schema,
        }
