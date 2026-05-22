"""Market-data REST surface. Generic, configurable, asset-class-aware."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.market_data import adapters  # noqa: F401 — triggers register_all
from app.market_data.registry import fetch as md_fetch, list_sources
from app.routers.auth import get_contractiq_user
from app.models.contractiq_models import ContractIQUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/market", tags=["contractiq-market"])


@router.get("/sources")
async def get_sources(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success(await list_sources(db))


@router.get("/sources/{slug}/snapshot")
async def snapshot_source(
    slug: str,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    history_days: int = Query(30, ge=1, le=365),
    metal: str | None = Query(None),
    symbol: str | None = Query(None),
) -> JSONResponse:
    params: dict[str, Any] = {"history_days": history_days}
    if metal:
        params["metal"] = metal
    if symbol:
        params["symbol"] = symbol
    result = await md_fetch(slug, db, params)
    if result.error:
        return error(result.error, 503)
    return success({
        "slug": slug,
        "ts": result.ts.isoformat(),
        "value": result.value,
        "unit": result.unit,
        "instrument_kind": result.instrument_kind,
        "payload": result.payload,
        "series": result.series,
    })


@router.get("/board")
async def market_board(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    asset_class: str | None = Query(None),
) -> JSONResponse:
    sources = await list_sources(db)
    if asset_class:
        sources = [s for s in sources if s["asset_class"] == asset_class]
    out = []
    for s in sources:
        r = await md_fetch(s["slug"], db, {"history_days": 5})
        out.append({
            "slug": s["slug"],
            "name": s["name"],
            "asset_class": s["asset_class"],
            "instrument_kind": s["instrument_kind"],
            "value": r.value,
            "unit": r.unit,
            "ts": r.ts.isoformat(),
        })
    return success(out)
