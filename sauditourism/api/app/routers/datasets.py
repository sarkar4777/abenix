"""Saudi Tourism Dataset Management — upload, CRUD, extraction via Abenix."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_utils import get_forge, parse_agent_json
from app.core.deps import get_db
from app.core.responses import error, success
from app.models.tourism_models import STDataset, STUser, DatasetType, DatasetStatus
from app.routers.auth import get_st_user

logger = logging.getLogger("sauditourism.datasets")
router = APIRouter(prefix="/api/st/datasets", tags=["st-datasets"])


TYPE_DETECTION = {
    "visitor": DatasetType.VISITOR_ARRIVALS,
    "arrival": DatasetType.VISITOR_ARRIVALS,
    "hotel": DatasetType.HOTEL_OCCUPANCY,
    "occupancy": DatasetType.HOTEL_OCCUPANCY,
    "revenue": DatasetType.REVENUE,
    "satisfaction": DatasetType.SATISFACTION_SURVEY,
    "survey": DatasetType.SATISFACTION_SURVEY,
    "strategy": DatasetType.STRATEGY_REPORT,
    "vision": DatasetType.STRATEGY_REPORT,
    "impact": DatasetType.IMPACT_STUDY,
    "neom": DatasetType.IMPACT_STUDY,
}


def _detect_type(filename: str) -> DatasetType:
    lower = filename.lower()
    for keyword, dtype in TYPE_DETECTION.items():
        if keyword in lower:
            return dtype
    return DatasetType.GENERAL




@router.get("")
async def list_datasets(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STDataset).where(STDataset.user_id == user.id).order_by(STDataset.created_at.desc())
    )
    datasets = result.scalars().all()
    return success([
        {
            "id": str(d.id),
            "title": d.title,
            "filename": d.filename,
            "dataset_type": d.dataset_type.value if d.dataset_type else "general",
            "status": d.status.value if d.status else "uploaded",
            "region": d.region,
            "period": d.period,
            "row_count": d.row_count,
            "file_size": d.file_size,
            "summary": d.summary,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in datasets
    ])


@router.get("/stats")
async def dataset_stats(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    datasets = (await db.execute(
        select(STDataset).where(STDataset.user_id == user.id)
    )).scalars().all()

    total_rows = sum(d.row_count or 0 for d in datasets)
    by_type = {}
    for d in datasets:
        t = d.dataset_type.value if d.dataset_type else "general"
        by_type[t] = by_type.get(t, 0) + 1

    return success({
        "total_datasets": len(datasets),
        "total_rows": total_rows,
        "by_type": by_type,
        "by_status": {
            s: sum(1 for d in datasets if d.status and d.status.value == s)
            for s in ["uploaded", "processing", "analyzed", "error"]
        },
    })


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    title: str = Form(""),
    region: str = Form(""),
    period: str = Form(""),
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        return error("No file provided", 400)

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    filename = file.filename
    detected_type = _detect_type(filename)

    dataset = STDataset(
        id=uuid.uuid4(),
        user_id=user.id,
        dataset_type=detected_type,
        title=title or filename.rsplit(".", 1)[0].replace("_", " ").title(),
        filename=filename,
        file_size=len(content),
        region=region or None,
        period=period or None,
        status=DatasetStatus.PROCESSING,
        raw_text=text[:500000],
    )
    db.add(dataset)
    await db.flush()

    # Extract via Abenix st-data-extractor agent
    try:
        forge, subject = get_forge(user)
        prompt = f"""Extract and analyze this tourism dataset.

FILENAME: {filename}
DETECTED TYPE: {detected_type.value}
CONTENT (first 30000 chars):
{text[:30000]}

Use the structured_extractor or document_parser tool to extract structured data.
Then return ONLY a JSON object:
{{
  "row_count": <number or null if not tabular>,
  "columns": [<column names>] or null,
  "summary": "<1-2 sentence description of the dataset>",
  "extracted_data": {{
    "preview": [<first 5 rows as objects>] or null,
    "numeric_stats": {{<column: {{min, max, mean, count}}>}} or null,
    "categorical_values": {{<column: [unique values]>}} or null,
    "key_findings": ["<finding 1>", "<finding 2>", ...]
  }}
}}"""
        result = await forge.execute("st-data-extractor", prompt, act_as=subject)
        parsed = parse_agent_json(result.output)
        if parsed:
            dataset.row_count = parsed.get("row_count")
            dataset.columns = parsed.get("columns")
            dataset.summary = parsed.get("summary", f"Processed: {filename}")
            dataset.extracted_data = parsed.get("extracted_data")
            dataset.status = DatasetStatus.ANALYZED
        else:
            dataset.summary = result.output[:500]
            dataset.status = DatasetStatus.ANALYZED
    except Exception as e:
        logger.exception("Abenix extraction failed: %s", e)
        dataset.status = DatasetStatus.ERROR
        dataset.summary = f"Extraction failed: {e}"

    await db.commit()
    await db.refresh(dataset)

    return success({
        "id": str(dataset.id),
        "title": dataset.title,
        "filename": dataset.filename,
        "dataset_type": dataset.dataset_type.value,
        "status": dataset.status.value,
        "row_count": dataset.row_count,
        "summary": dataset.summary,
    })


@router.get("/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STDataset).where(STDataset.id == uuid.UUID(dataset_id), STDataset.user_id == user.id)
    )
    d = result.scalar_one_or_none()
    if not d:
        return error("Dataset not found", 404)
    return success({
        "id": str(d.id),
        "title": d.title,
        "filename": d.filename,
        "dataset_type": d.dataset_type.value,
        "status": d.status.value,
        "region": d.region,
        "period": d.period,
        "row_count": d.row_count,
        "columns": d.columns,
        "file_size": d.file_size,
        "summary": d.summary,
        "extracted_data": d.extracted_data,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    })


@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(STDataset).where(STDataset.id == uuid.UUID(dataset_id), STDataset.user_id == user.id)
    )
    d = result.scalar_one_or_none()
    if not d:
        return error("Dataset not found", 404)
    await db.delete(d)
    await db.commit()
    return success({"deleted": True})


@router.post("/seed")
async def seed_test_data(
    user: STUser = Depends(get_st_user),
    db: AsyncSession = Depends(get_db),
):
    """Seed all test-data CSVs/TXTs — extraction done via Abenix."""
    test_dir = Path(__file__).resolve().parent.parent.parent.parent / "test-data"
    seeded = []

    for f in sorted(test_dir.glob("*.*")):
        if f.suffix not in (".csv", ".txt"):
            continue
        existing = (await db.execute(
            select(STDataset).where(STDataset.user_id == user.id, STDataset.filename == f.name)
        )).scalar_one_or_none()
        if existing:
            seeded.append({"filename": f.name, "status": "already_exists"})
            continue

        content = f.read_text(encoding="utf-8")
        detected_type = _detect_type(f.name)

        dataset = STDataset(
            id=uuid.uuid4(),
            user_id=user.id,
            dataset_type=detected_type,
            title=f.stem.replace("_", " ").title(),
            filename=f.name,
            file_size=len(content.encode()),
            status=DatasetStatus.PROCESSING,
            raw_text=content[:500000],
        )
        db.add(dataset)
        await db.flush()

        # Extract via Abenix
        try:
            forge, subject = get_forge(user)
            prompt = f"""Extract and analyze this tourism dataset.
FILENAME: {f.name}
TYPE: {detected_type.value}
CONTENT (first 20000 chars):
{content[:20000]}

Return ONLY JSON: {{"row_count": <int|null>, "columns": [<str>]|null, "summary": "<description>", "extracted_data": {{"key_findings": [<str>]}}}}"""
            result = await forge.execute("st-data-extractor", prompt, act_as=subject)
            parsed = parse_agent_json(result.output)
            if parsed:
                dataset.row_count = parsed.get("row_count")
                dataset.columns = parsed.get("columns")
                dataset.summary = parsed.get("summary", f"Processed: {f.name}")
                dataset.extracted_data = parsed.get("extracted_data")
            else:
                dataset.summary = f"Processed: {f.name}"
            dataset.status = DatasetStatus.ANALYZED
        except Exception as e:
            logger.warning("Abenix extraction failed for %s: %s", f.name, e)
            dataset.summary = f"Upload complete: {f.name}"
            dataset.status = DatasetStatus.ANALYZED

        seeded.append({"filename": f.name, "status": "seeded", "rows": dataset.row_count})

    await db.commit()
    return success({"seeded": seeded})
