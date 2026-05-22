"""Market data subsystem. Adapter-per-source pattern. UI-configurable registry."""

from app.market_data.registry import fetch, list_sources, snapshot, sync_source

__all__ = ["fetch", "list_sources", "snapshot", "sync_source"]
