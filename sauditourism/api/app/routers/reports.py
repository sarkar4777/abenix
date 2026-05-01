"""Saudi Tourism Reports — auto-generated via Abenix st-report-generator agent."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_utils import get_forge
from app.core.deps import get_db
from app.core.responses import error, success
from app.models.tourism_models import STReport, STDataset, STUser
from app.routers.auth import get_st_user

logger = logging.getLogger("sauditourism.reports")
router = APIRouter(prefix="/api/st/reports", tags=["st-reports"])


REPORT_TYPES = {
    "executive_briefing": {
        "title": "Executive Briefing",
        "description": "High-level summary of tourism performance with key metrics and trends",
        "agent_prompt": "Generate a comprehensive executive briefing for the KSA Ministry of Tourism. Include KPIs, regional performance, visitor trends, revenue analysis, and strategic recommendations. Use financial_calculator for all derived metrics.",
    },
    "regional_comparison": {
        "title": "Regional Comparison Report",
        "description": "Side-by-side comparison of all KSA tourism regions",
        "agent_prompt": "Create a detailed comparison of all KSA tourism regions including visitors, revenue, occupancy, and growth rates. Use financial_calculator to compute growth rates and rankings.",
    },
    "visitor_segmentation": {
        "title": "Visitor Segmentation Analysis",
        "description": "Breakdown by origin (domestic/GCC/international) and purpose (religious/leisure/business)",
        "agent_prompt": "Analyze visitor segmentation by origin (domestic/GCC/international) and purpose (religious/leisure/business). Include market share, growth trends, and spending patterns. Use financial_calculator for percentages and trends.",
    },
    "revenue_attribution": {
        "title": "Revenue Attribution Report",
        "description": "Where tourism money is spent: accommodation, F&B, transport, attractions, shopping",
        "agent_prompt": "Generate a revenue attribution analysis showing where tourism spending flows: accommodation, F&B, transport, attractions, shopping, etc. Use financial_calculator for sector shares and growth rates.",
    },
    "seasonal_analysis": {
        "title": "Seasonal Performance Analysis",
        "description": "Monthly/quarterly trends with seasonality patterns",
        "agent_prompt": "Analyze seasonal patterns in KSA tourism: monthly trends, peak/trough identification, Hajj/Umrah impact, seasonal pricing opportunities. Use financial_calculator for trend decomposition.",
    },
}


def _build_data_context(datasets: list[STDataset], max_chars: int = 50000) -> str:
    parts = []
    char_count = 0
    for d in datasets:
        if not d.raw_text:
            continue
        section = f"\n=== DATASET: {d.title} (type={d.dataset_type.value if d.dataset_type else 'general'}) ===\n"
        section += d.raw_text[:25000]
        if char_count + len(section) > max_chars:
            break
        parts.append(section)
        char_count += len(section)
    return "".join(parts) if parts else "NO DATA"


@router.get("/types")
async def get_report_types():
    # Strip agent_prompt from response
    clean = {k: {kk: vv for kk, vv in v.items() if kk != "agent_prompt"} for k, v in REPORT_TYPES.items()}
    return success(clean)


@router.post("/generate")
async def generate_report(
    body: dict,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    report_type = body.get("type", "executive_briefing")
    if report_type not in REPORT_TYPES:
        return error(f"Unknown report type: {report_type}", 400)

    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()

    if not datasets:
        return error("No datasets uploaded. Please upload tourism data first.", 400)

    preset = REPORT_TYPES[report_type]
    data_context = _build_data_context(datasets)
    forge, subject = get_forge(user)

    prompt = f"""{preset['agent_prompt']}

DATA FROM USER'S UPLOADED DATASETS:
{data_context}

FORMAT: Generate the report in rich Markdown format with:
- Executive summary at the top
- Tables for comparisons
- Bullet points for recommendations
- Bold key metrics
- Section headers for each topic

Use your tools (financial_calculator, structured_extractor, graph_builder) for all computations.
Do NOT make up data — use only what's in the datasets above."""

    result = await forge.execute("st-report-generator", prompt, act_as=subject)

    report = STReport(
        id=uuid.uuid4(),
        user_id=user.id,
        title=preset["title"],
        report_type=report_type,
        content=result.output,
        data={"agent_cost": result.cost, "agent_tokens": result.input_tokens + result.output_tokens},
    )
    db.add(report)
    await db.commit()

    return success({
        "id": str(report.id),
        "title": report.title,
        "type": report_type,
        "content": result.output,
        "agent_cost": result.cost,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    })


@router.get("")
async def list_reports(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STReport).where(STReport.user_id == user.id).order_by(STReport.created_at.desc())
    )
    reports = result.scalars().all()
    return success([
        {"id": str(r.id), "title": r.title, "type": r.report_type, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in reports
    ])


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STReport).where(STReport.id == uuid.UUID(report_id), STReport.user_id == user.id)
    )
    r = result.scalar_one_or_none()
    if not r:
        return error("Report not found", 404)
    return success({
        "id": str(r.id),
        "title": r.title,
        "type": r.report_type,
        "content": r.content,
        "data": r.data,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    })
