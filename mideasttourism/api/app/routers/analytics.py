"""Mideast Tourism Analytics — agent results cached in DB for instant page loads."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import success
from app.core.agent_utils import get_forge, parse_agent_json
from app.models.tourism_models import STDataset, STUser, STAnalyticsResult
from app.routers.auth import get_st_user

logger = logging.getLogger("mideasttourism.analytics")
router = APIRouter(prefix="/api/st/analytics", tags=["st-analytics"])

    # SDK imports via agent_utils

CACHE_TTL_MINUTES = 60  # 1 hour

GULF_REGIONS = [
    {"id": "dubai", "name": "Dubai", "lat": 25.2048, "lng": 55.2708},
    {"id": "doha", "name": "Doha", "lat": 25.2854, "lng": 51.531},
    {"id": "muscat", "name": "Muscat", "lat": 23.588, "lng": 58.3829},
    {"id": "eastern", "name": "Northern Emirates", "lat": 25.7895, "lng": 55.9432},
    {"id": "abudhabi", "name": "Abu Dhabi", "lat": 24.4539, "lng": 54.3773},
    {"id": "lusail", "name": "Lusail", "lat": 25.43, "lng": 51.49},
    {"id": "nizwa", "name": "Nizwa", "lat": 22.9333, "lng": 57.5333},
    {"id": "salalah", "name": "Salalah", "lat": 17.0151, "lng": 54.0924},
    {"id": "sharjah", "name": "Sharjah", "lat": 25.3463, "lng": 55.4209},
]


    # get_forge and parse_agent_json imported from app.core.agent_utils


def _build_data_csv_block(datasets: list[STDataset], max_chars: int = 50000) -> str:
    parts = []
    char_count = 0
    for d in datasets:
        if not d.raw_text or not d.filename:
            continue
        header = f"\n=== DATASET: {d.title} (type={d.dataset_type.value if d.dataset_type else 'general'}, file={d.filename}) ===\n"
        if d.filename.endswith(".csv"):
            section = header + d.raw_text[:30000]
        else:
            section = header + d.raw_text[:8000]
        if char_count + len(section) > max_chars:
            break
        parts.append(section)
        char_count += len(section)
    return "".join(parts) if parts else "NO DATA UPLOADED YET"


def _parse_agent_response(output: str) -> dict:
    if "```json" in output:
        try:
            start = output.index("```json") + 7
            end = output.index("```", start)
            return json.loads(output[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
    try:
        return json.loads(output)
    except (json.JSONDecodeError, ValueError):
        pass
    return {"text": output}


async def _get_cached(
    db: AsyncSession, user_id: uuid.UUID, analysis_type: str
) -> dict | None:
    """Return cached analytics result if fresh enough."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)
    result = await db.execute(
        select(STAnalyticsResult)
        .where(
            STAnalyticsResult.user_id == user_id,
            STAnalyticsResult.analysis_type == analysis_type,
            STAnalyticsResult.created_at >= cutoff,
        )
        .order_by(STAnalyticsResult.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        return {
            "cached": True,
            "cached_at": row.created_at.isoformat() if row.created_at else None,
            "results": row.results,
        }
    return None


async def _save_cache(
    db: AsyncSession, user_id: uuid.UUID, dataset_id: uuid.UUID | None,
    analysis_type: str, results: dict, summary: str = "",
):
    """Save agent result to cache."""
    ar = STAnalyticsResult(
        id=uuid.uuid4(),
        dataset_id=dataset_id or uuid.uuid4(),
        user_id=user_id,
        analysis_type=analysis_type,
        results=results,
        summary=summary,
    )
    db.add(ar)
    await db.commit()


@router.get("/dashboard")
async def dashboard_kpis(
    refresh: bool = Query(False),
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard KPIs — cached, refreshable."""
    # Check cache first (unless refresh forced)
    if not refresh:
        cached = await _get_cached(db, user.id, "dashboard")
        if cached:
            return success({**cached["results"], "_cached": True, "_cached_at": cached["cached_at"]})

    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()

    if not datasets:
        return success({"kpis": {}, "monthly_arrivals": [], "revenue_by_sector": [], "region_visitors": [], "top_countries": [], "purpose_breakdown": []})

    data_block = _build_data_csv_block(datasets)
    forge, subject = get_forge(user)

    prompt = f"""Analyze this regional tourism data and return a JSON dashboard summary.

{data_block}

Return ONLY a JSON object (no markdown, no explanation) with this exact structure:
{{
  "kpis": {{
    "total_visitors": <number>,
    "total_revenue_usd": <number>,
    "avg_hotel_occupancy": <number 0-100>,
    "avg_satisfaction": <number 0-5>,
    "total_datasets": {len(datasets)},
    "total_data_rows": <number>
  }},
  "monthly_arrivals": [{{"month": "<YYYY-MM>", "visitors": <number>}}, ...],
  "revenue_by_sector": [{{"sector": "<name>", "revenue": <number>}}, ...],
  "revenue_by_region": [{{"region": "<name>", "revenue": <number>}}, ...],
  "region_visitors": [{{"region": "<name>", "visitors": <number>}}, ...],
  "top_countries": [{{"country": "<name>", "visitors": <number>}}, ...],
  "purpose_breakdown": [{{"purpose": "<name>", "visitors": <number>}}, ...]
}}

Use the financial_calculator tool for any derived metrics. Sort arrays by value descending."""

    result = await forge.execute("st-analytics", prompt, act_as=subject)
    parsed = parse_agent_json(result.output)

    # Save to cache
    first_ds = datasets[0] if datasets else None
    await _save_cache(db, user.id, first_ds.id if first_ds else None, "dashboard", parsed, "Dashboard KPIs")

    return success({**parsed, "_cached": False, "_agent_cost": result.cost})


@router.get("/regional")
async def regional_analytics(
    refresh: bool = Query(False),
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    if not refresh:
        cached = await _get_cached(db, user.id, "regional")
        if cached:
            return success({**cached["results"], "_cached": True, "_cached_at": cached["cached_at"]})

    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()

    if not datasets:
        return success({"regions": []})

    data_block = _build_data_csv_block(datasets)
    forge, subject = get_forge(user)

    regions_json = json.dumps(GULF_REGIONS)
    prompt = f"""Analyze this regional tourism data by region.

{data_block}

regions: {regions_json}

Return ONLY JSON:
{{
  "regions": [
    {{
      "id": "<region_id>", "name": "<Region Name>", "lat": <lat>, "lng": <lng>,
      "visitors": <total visitors>, "revenue": <total revenue USD>,
      "avg_occupancy": <avg hotel occupancy %>,
      "monthly_trend": [{{"month": "<YYYY-MM>", "visitors": <number>}}],
      "top_attractions": ["<attraction1>"],
      "yoy_growth": <percentage>
    }}
  ]
}}
Sort by visitor count descending. Use financial_calculator for growth rates."""

    result = await forge.execute("st-analytics", prompt, act_as=subject)
    parsed = parse_agent_json(result.output)

    first_ds = datasets[0] if datasets else None
    await _save_cache(db, user.id, first_ds.id if first_ds else None, "regional", parsed, "Regional analytics")

    return success({**parsed, "_cached": False, "_agent_cost": result.cost})


@router.get("/deep")
async def deep_analytics(
    refresh: bool = Query(False),
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    if not refresh:
        cached = await _get_cached(db, user.id, "deep")
        if cached:
            return success({**cached["results"], "_cached": True, "_cached_at": cached["cached_at"]})

    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()

    if not datasets:
        return success({"time_series": {}, "segmentation": {}, "revenue_attribution": [], "satisfaction": {}})

    data_block = _build_data_csv_block(datasets)
    forge, subject = get_forge(user)

    prompt = f"""Perform deep analytics on this regional tourism data.

{data_block}

Return ONLY JSON:
{{
  "time_series": {{
    "monthly": [{{"month": "<YYYY-MM>", "visitors": <number>}}],
    "quarterly": [{{"quarter": "<YYYY-Q#>", "visitors": <number>}}],
    "growth_rate_yoy": <percentage>
  }},
  "segmentation": {{
    "by_origin": {{"domestic": <number>, "gcc": <number>, "international": <number>}},
    "by_purpose": {{"religious": <number>, "leisure": <number>, "business": <number>}}
  }},
  "revenue_attribution": [
    {{"sector": "<name>", "revenue": <number>, "pct_share": <percentage>}}
  ],
  "satisfaction": {{
    "avg_rating": <number 0-5>,
    "rating_distribution": {{"1": <count>, "2": <count>, "3": <count>, "4": <count>, "5": <count>}},
    "top_complaints": ["<issue>"],
    "top_praise": ["<praise>"]
  }}
}}
Use financial_calculator for all derived metrics."""

    result = await forge.execute("st-analytics", prompt, act_as=subject)
    parsed = parse_agent_json(result.output)

    first_ds = datasets[0] if datasets else None
    await _save_cache(db, user.id, first_ds.id if first_ds else None, "deep", parsed, "Deep analytics")

    return success({**parsed, "_cached": False, "_agent_cost": result.cost})


@router.get("/regions")
async def list_regions():
    return success(GULF_REGIONS)
