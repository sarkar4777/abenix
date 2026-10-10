from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from models.code_asset_invocation import CodeAssetInvocation
from models.ml_model_invocation import MLModelInvocation
from models.kb_query_invocation import KBQueryInvocation
from models.code_asset import CodeAsset
from models.ml_model import MLModel
from models.user import User

router = APIRouter(tags=["invocations"])

_REDIS_URL = os.environ.get("REDIS_URL", "")
_PUBSUB_CHANNEL_PREFIX = "invocations:"


async def _invocation_sse(kind: str, resource_id: str):
    yield f"event: start\ndata: {json.dumps({'kind': kind, 'resource_id': str(resource_id)})}\n\n"
    if not _REDIS_URL:
        yield 'event: closed\ndata: {"reason": "redis not configured"}\n\n'
        return
    try:
        import redis.asyncio as redis_async  # type: ignore

        client = redis_async.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'reason': str(e)})}\n\n"
        return
    pubsub = client.pubsub()
    channel = f"{_PUBSUB_CHANNEL_PREFIX}{kind}:{resource_id}"
    try:
        await pubsub.subscribe(channel)
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
            if msg is None:
                yield ": heartbeat\n\n"
                continue
            data = msg.get("data")
            if data:
                yield f"event: invocation\ndata: {data}\n\n"
    except asyncio.CancelledError:
        return
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await client.aclose()
        except Exception:
            pass


def _window_to_delta(window: str) -> timedelta:
    window = (window or "24h").lower().strip()
    if window.endswith("h"):
        try:
            return timedelta(hours=int(window[:-1]))
        except ValueError:
            return timedelta(hours=24)
    if window.endswith("d"):
        try:
            return timedelta(days=int(window[:-1]))
        except ValueError:
            return timedelta(days=1)
    return timedelta(hours=24)


@router.get("/api/code-assets/{asset_id}/invocations")
async def list_code_asset_invocations(
    asset_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(ok|error)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    asset = (
        await db.execute(select(CodeAsset).where(CodeAsset.id == asset_id))
    ).scalar_one_or_none()
    if not asset:
        return error("Code asset not found", 404)
    if asset.tenant_id != user.tenant_id:
        return error("Code asset not found", 404)

    q = select(CodeAssetInvocation).where(CodeAssetInvocation.code_asset_id == asset_id)
    if status == "ok":
        q = q.where(CodeAssetInvocation.is_error.is_(False))
    elif status == "error":
        q = q.where(CodeAssetInvocation.is_error.is_(True))
    q = (
        q.order_by(CodeAssetInvocation.created_at.desc(), CodeAssetInvocation.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).scalars().all()
    total_q = select(func.count(CodeAssetInvocation.id)).where(
        CodeAssetInvocation.code_asset_id == asset_id
    )
    total = (await db.execute(total_q)).scalar() or 0
    items = [
        {
            "id": str(r.id),
            "code_asset_id": str(r.code_asset_id),
            "execution_id": str(r.execution_id) if r.execution_id else None,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "duration_ms": r.duration_ms,
            "is_error": r.is_error,
            "exit_code": r.exit_code,
            "error_message": r.error_message,
            "input_payload": r.input_payload,
            "output": r.output,
            "stdout": r.stdout,
            "stderr": r.stderr,
            "image_tag": r.image_tag,
            "schema_validated": r.schema_validated,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return success({"items": items, "total": total})


@router.get("/api/code-assets/{asset_id}/invocations/stream")
async def stream_code_asset_invocations(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    asset = (
        await db.execute(select(CodeAsset).where(CodeAsset.id == asset_id))
    ).scalar_one_or_none()
    if not asset:
        return StreamingResponse(
            iter([b'event: error\ndata: {"reason":"not_found"}\n\n']),
            media_type="text/event-stream",
        )
    if asset.tenant_id != user.tenant_id and (
        getattr(user.role, "value", str(user.role)).lower() != "admin"
    ):
        return StreamingResponse(
            iter([b'event: error\ndata: {"reason":"forbidden"}\n\n']),
            media_type="text/event-stream",
        )
    await db.close()
    return StreamingResponse(
        _invocation_sse("code_asset", str(asset_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/code-assets/{asset_id}/stats")
async def code_asset_stats(
    asset_id: uuid.UUID,
    window: str = Query("24h"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    asset = (
        await db.execute(select(CodeAsset).where(CodeAsset.id == asset_id))
    ).scalar_one_or_none()
    if not asset:
        return error("Code asset not found", 404)
    if asset.tenant_id != user.tenant_id:
        return error("Code asset not found", 404)

    since = datetime.now(timezone.utc) - _window_to_delta(window)
    base = select(CodeAssetInvocation).where(
        CodeAssetInvocation.code_asset_id == asset_id,
        CodeAssetInvocation.created_at >= since,
    )
    total = (
        await db.execute(
            select(func.count(CodeAssetInvocation.id)).select_from(base.subquery())
        )
    ).scalar() or 0
    errors = (
        await db.execute(
            select(func.count(CodeAssetInvocation.id)).select_from(
                base.where(CodeAssetInvocation.is_error.is_(True)).subquery()
            )
        )
    ).scalar() or 0
    avg_ms = (
        await db.execute(
            select(func.avg(CodeAssetInvocation.duration_ms)).select_from(
                base.subquery()
            )
        )
    ).scalar()
    by_agent_q = (
        select(
            CodeAssetInvocation.agent_id, func.count(CodeAssetInvocation.id).label("c")
        )
        .where(
            CodeAssetInvocation.code_asset_id == asset_id,
            CodeAssetInvocation.created_at >= since,
            CodeAssetInvocation.agent_id.isnot(None),
        )
        .group_by(CodeAssetInvocation.agent_id)
        .order_by(func.count(CodeAssetInvocation.id).desc())
        .limit(5)
    )
    by_agent_rows = (await db.execute(by_agent_q)).all()
    return success(
        {
            "window": window,
            "total": total,
            "errors": errors,
            "success_rate": (1.0 - (errors / total)) if total else None,
            "avg_duration_ms": int(avg_ms) if avg_ms else None,
            "top_agents": [
                {"agent_id": str(r[0]), "count": r[1]} for r in by_agent_rows
            ],
        }
    )


@router.get("/api/ml-models/invocations")
async def list_all_ml_invocations(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(ok|error)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = (
        select(MLModelInvocation)
        .join(MLModel, MLModelInvocation.ml_model_id == MLModel.id)
        .where(MLModel.tenant_id == user.tenant_id)
    )
    if status == "ok":
        q = q.where(MLModelInvocation.is_error.is_(False))
    elif status == "error":
        q = q.where(MLModelInvocation.is_error.is_(True))
    q = (
        q.order_by(MLModelInvocation.created_at.desc(), MLModelInvocation.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).scalars().all()
    items = [
        {
            "id": str(r.id),
            "ml_model_id": str(r.ml_model_id),
            "execution_id": str(r.execution_id) if r.execution_id else None,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "operation": r.operation,
            "duration_ms": r.duration_ms,
            "is_error": r.is_error,
            "error_message": r.error_message,
            "deployment_type": r.deployment_type,
            "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return success({"items": items, "total": len(items)})


@router.get("/api/ml-models/{model_id}/invocations")
async def list_ml_model_invocations(
    model_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(ok|error)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = (
        await db.execute(select(MLModel).where(MLModel.id == model_id))
    ).scalar_one_or_none()
    if not m:
        return error("Model not found", 404)
    if m.tenant_id != user.tenant_id:
        return error("Model not found", 404)

    q = select(MLModelInvocation).where(MLModelInvocation.ml_model_id == model_id)
    if status == "ok":
        q = q.where(MLModelInvocation.is_error.is_(False))
    elif status == "error":
        q = q.where(MLModelInvocation.is_error.is_(True))
    q = (
        q.order_by(MLModelInvocation.created_at.desc(), MLModelInvocation.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).scalars().all()
    total = (
        await db.execute(
            select(func.count(MLModelInvocation.id)).where(
                MLModelInvocation.ml_model_id == model_id
            )
        )
    ).scalar() or 0
    items = [
        {
            "id": str(r.id),
            "ml_model_id": str(r.ml_model_id),
            "execution_id": str(r.execution_id) if r.execution_id else None,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "operation": r.operation,
            "duration_ms": r.duration_ms,
            "is_error": r.is_error,
            "error_message": r.error_message,
            "input_payload": r.input_payload,
            "output": r.output,
            "predicted_class": r.predicted_class,
            "confidence": r.confidence,
            "deployment_type": r.deployment_type,
            "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return success({"items": items, "total": total})


@router.get("/api/ml-models/{model_id}/invocations/stream")
async def stream_ml_model_invocations(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    m = (
        await db.execute(select(MLModel).where(MLModel.id == model_id))
    ).scalar_one_or_none()
    if not m:
        return StreamingResponse(
            iter([b'event: error\ndata: {"reason":"not_found"}\n\n']),
            media_type="text/event-stream",
        )
    if m.tenant_id != user.tenant_id and (
        getattr(user.role, "value", str(user.role)).lower() != "admin"
    ):
        return StreamingResponse(
            iter([b'event: error\ndata: {"reason":"forbidden"}\n\n']),
            media_type="text/event-stream",
        )
    await db.close()
    return StreamingResponse(
        _invocation_sse("ml_model", str(model_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/ml-models/{model_id}/stats")
async def ml_model_stats(
    model_id: uuid.UUID,
    window: str = Query("24h"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = (
        await db.execute(select(MLModel).where(MLModel.id == model_id))
    ).scalar_one_or_none()
    if not m:
        return error("Model not found", 404)
    if m.tenant_id != user.tenant_id:
        return error("Model not found", 404)

    since = datetime.now(timezone.utc) - _window_to_delta(window)
    where = [
        MLModelInvocation.ml_model_id == model_id,
        MLModelInvocation.created_at >= since,
    ]
    total = (
        await db.execute(select(func.count(MLModelInvocation.id)).where(*where))
    ).scalar() or 0
    errors = (
        await db.execute(
            select(func.count(MLModelInvocation.id)).where(
                *where, MLModelInvocation.is_error.is_(True)
            )
        )
    ).scalar() or 0
    avg_ms = (
        await db.execute(select(func.avg(MLModelInvocation.duration_ms)).where(*where))
    ).scalar()
    total_cost = (
        await db.execute(
            select(func.coalesce(func.sum(MLModelInvocation.cost_usd), 0)).where(*where)
        )
    ).scalar() or 0
    by_agent_q = (
        select(MLModelInvocation.agent_id, func.count(MLModelInvocation.id).label("c"))
        .where(*where, MLModelInvocation.agent_id.isnot(None))
        .group_by(MLModelInvocation.agent_id)
        .order_by(func.count(MLModelInvocation.id).desc())
        .limit(5)
    )
    by_agent_rows = (await db.execute(by_agent_q)).all()
    return success(
        {
            "window": window,
            "total": total,
            "errors": errors,
            "success_rate": (1.0 - (errors / total)) if total else None,
            "avg_duration_ms": int(avg_ms) if avg_ms else None,
            "total_cost_usd": float(total_cost),
            "top_agents": [
                {"agent_id": str(r[0]), "count": r[1]} for r in by_agent_rows
            ],
        }
    )


@router.get("/api/knowledge-collections/{collection_id}/queries")
async def list_kb_query_invocations(
    collection_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = (
        select(KBQueryInvocation)
        .where(
            KBQueryInvocation.kb_collection_id == collection_id,
            KBQueryInvocation.tenant_id == user.tenant_id,
        )
        .order_by(KBQueryInvocation.created_at.desc(), KBQueryInvocation.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).scalars().all()
    total = (
        await db.execute(
            select(func.count(KBQueryInvocation.id)).where(
                KBQueryInvocation.kb_collection_id == collection_id,
                KBQueryInvocation.tenant_id == user.tenant_id,
            )
        )
    ).scalar() or 0
    items = [
        {
            "id": str(r.id),
            "kb_collection_id": str(r.kb_collection_id) if r.kb_collection_id else None,
            "execution_id": str(r.execution_id) if r.execution_id else None,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "query_text": r.query_text,
            "search_mode": r.search_mode,
            "top_k": r.top_k,
            "hit_count": r.hit_count,
            "duration_ms": r.duration_ms,
            "is_error": r.is_error,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return success({"items": items, "total": total})


@router.get("/api/knowledge-collections/{collection_id}/queries/stream")
async def stream_kb_query_invocations(
    collection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # same session the auth lookup used, release it before streaming
    await db.close()
    return StreamingResponse(
        _invocation_sse("kb_query", str(collection_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
