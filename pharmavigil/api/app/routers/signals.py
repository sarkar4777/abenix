"""Signal board and the sample dataset.

The board aggregates drug-event pairs across the case history. Numbers come
from what the pipeline recorded on each case, not from a recomputation here —
the arithmetic lives in the disproportionality code asset so there is one
implementation, and this view only ranks what it produced.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.core.store import CaseStore
from app.routers._deps import get_store

logger = logging.getLogger("pharmavigil.signals")
router = APIRouter(prefix="/api/pv", tags=["pv-signals"])

def _samples_dir() -> Path:
    """Where the sample reports live.

    In the image they sit at /app/test-data. Running `python main.py` from a
    clone they are two levels up, in pharmavigil/test-data. parents[3] was
    neither — from app/routers/ it resolves to the filesystem root.
    """
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[2] / "test-data",      # /app/test-data (container)
        here.parents[3] / "test-data",      # pharmavigil/api/test-data (repo)
    ):
        if candidate.is_dir():
            return candidate
    return here.parents[2] / "test-data"


SAMPLES = _samples_dir()


def _ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None, "meta": None}


@router.get("/signals")
async def signal_board(store: CaseStore = Depends(get_store)):
    return _ok(await store.signal_board())


@router.get("/samples")
async def list_samples():
    """Reports shipped with the app so the demo has something to chew on."""
    path = SAMPLES / "sample_reports.json"
    if not path.exists():
        return _ok([])
    try:
        return _ok(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("sample reports unreadable: %s", exc)
        return _ok([])
