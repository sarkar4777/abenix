"""Seeds store files the same durable way uploads do."""

from __future__ import annotations

import sys
from pathlib import Path


async def mirror_quietly(path: str | Path) -> None:
    """Mirror a seeded file to object storage, never failing the seed over it."""
    here = Path(__file__).resolve()
    for root in (here.parents[3] / "apps" / "api", Path("/app/apps/api"), Path("/app")):
        if (root / "app" / "core" / "artifact_store.py").is_file() and str(
            root
        ) not in sys.path:
            sys.path.insert(0, str(root))
    try:
        from app.core.artifact_store import mirror  # type: ignore
    except Exception:
        return
    try:
        await mirror(path)
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not mirror {Path(path).name} to object storage: {e}")
