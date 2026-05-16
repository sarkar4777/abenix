from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_DB_URL = os.environ.get("DATABASE_URL", "")
_REDIS_URL = os.environ.get("REDIS_URL", "")
_MAX_PAYLOAD_CHARS = 8000
_MAX_TEXT_CHARS = 16000
_PUBSUB_CHANNEL_PREFIX = "invocations:"


async def _publish_event(kind: str, resource_id: str, event: dict) -> None:
    if not _REDIS_URL or not resource_id:
        return
    try:
        import redis.asyncio as redis_async  # type: ignore

        client = redis_async.from_url(_REDIS_URL, decode_responses=True)
        channel = f"{_PUBSUB_CHANNEL_PREFIX}{kind}:{resource_id}"
        await client.publish(channel, json.dumps(event, default=str))
        await client.aclose()
    except Exception as e:
        logger.debug("invocation_log.publish %s/%s failed: %s", kind, resource_id, e)


def _truncate_json(value: Any) -> Any:
    if value is None:
        return None
    try:
        s = json.dumps(value, default=str)
    except Exception:
        return {"_unserialisable": True}
    if len(s) <= _MAX_PAYLOAD_CHARS:
        return value
    return {"_truncated": True, "preview": s[:_MAX_PAYLOAD_CHARS]}


def _truncate_text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    if len(s) > _MAX_TEXT_CHARS:
        return s[:_MAX_TEXT_CHARS] + f"\n…(truncated, {len(s)} total chars)"
    return s


async def _engine():
    if not _DB_URL:
        return None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        return create_async_engine(_DB_URL, pool_pre_ping=True, pool_size=1)
    except Exception as e:
        logger.debug("invocation_log: engine init failed: %s", e)
        return None


async def record_code_asset(
    *,
    tenant_id: str | None,
    code_asset_id: str,
    execution_id: str | None,
    agent_id: str | None,
    input_payload: Any,
    output: Any,
    stdout: str | None,
    stderr: str | None,
    exit_code: int | None,
    duration_ms: int | None,
    is_error: bool,
    error_message: str | None,
    image_tag: str | None = None,
    schema_validated: bool = False,
    caller_source: str | None = "agent_runtime",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    try:
        from engine import metrics

        status = "error" if is_error else "ok"
        metrics.CODE_ASSET_INVOCATIONS_TOTAL.labels(
            code_asset_id=str(code_asset_id), status=status
        ).inc()
        if duration_ms is not None:
            metrics.CODE_ASSET_DURATION_SECONDS.labels(
                code_asset_id=str(code_asset_id)
            ).observe(duration_ms / 1000.0)
    except Exception:
        pass

    eng = await _engine()
    if eng is None or not tenant_id or not code_asset_id:
        return
    new_id = str(uuid.uuid4())
    try:
        from sqlalchemy import text as sql_text

        async with eng.begin() as conn:
            await conn.execute(
                sql_text(
                    "INSERT INTO code_asset_invocations "
                    "(id, tenant_id, code_asset_id, execution_id, agent_id, input_payload, output, "
                    "stdout, stderr, exit_code, duration_ms, is_error, error_message, image_tag, "
                    "schema_validated, caller_source, started_at, completed_at, created_at, updated_at) "
                    "VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:aid AS uuid), "
                    "CAST(:eid AS uuid), CAST(:agid AS uuid), CAST(:input AS jsonb), CAST(:output AS jsonb), "
                    ":stdout, :stderr, :exit_code, :duration_ms, :is_error, :error_message, :image_tag, "
                    ":schema_validated, :caller_source, :started_at, :completed_at, NOW(), NOW())"
                ),
                {
                    "id": new_id,
                    "tid": str(tenant_id),
                    "aid": str(code_asset_id),
                    "eid": str(execution_id) if execution_id else None,
                    "agid": str(agent_id) if agent_id else None,
                    "input": (
                        json.dumps(_truncate_json(input_payload), default=str)
                        if input_payload is not None
                        else None
                    ),
                    "output": (
                        json.dumps(_truncate_json(output), default=str)
                        if output is not None
                        else None
                    ),
                    "stdout": _truncate_text(stdout),
                    "stderr": _truncate_text(stderr),
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    "is_error": bool(is_error),
                    "error_message": _truncate_text(error_message),
                    "image_tag": image_tag,
                    "schema_validated": bool(schema_validated),
                    "caller_source": caller_source,
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )
    except Exception as e:
        logger.debug("invocation_log.code_asset insert failed: %s", e)
    finally:
        try:
            await eng.dispose()
        except Exception:
            pass

    try:
        await _publish_event(
            "code_asset",
            str(code_asset_id),
            {
                "id": new_id,
                "code_asset_id": str(code_asset_id),
                "agent_id": agent_id,
                "execution_id": execution_id,
                "duration_ms": duration_ms,
                "is_error": bool(is_error),
                "exit_code": exit_code,
                "error_message": _truncate_text(error_message),
                "created_at": (completed_at or datetime.utcnow()).isoformat(),
            },
        )
    except Exception:
        pass


async def record_ml_model(
    *,
    tenant_id: str | None,
    ml_model_id: str,
    execution_id: str | None,
    agent_id: str | None,
    operation: str,
    input_payload: Any,
    output: Any,
    predicted_class: str | None,
    confidence: float | None,
    duration_ms: int | None,
    is_error: bool,
    error_message: str | None,
    deployment_type: str | None = None,
    cost_usd: float | None = None,
    caller_source: str | None = "agent_runtime",
) -> None:
    try:
        from engine import metrics

        status = "error" if is_error else "ok"
        metrics.ML_MODEL_INVOCATIONS_TOTAL.labels(
            ml_model_id=str(ml_model_id),
            operation=operation or "predict",
            status=status,
        ).inc()
        if duration_ms is not None:
            metrics.ML_MODEL_DURATION_SECONDS.labels(
                ml_model_id=str(ml_model_id),
                operation=operation or "predict",
            ).observe(duration_ms / 1000.0)
        if cost_usd:
            metrics.ML_MODEL_COST_USD_TOTAL.labels(ml_model_id=str(ml_model_id)).inc(
                float(cost_usd)
            )
    except Exception:
        pass

    eng = await _engine()
    if eng is None or not tenant_id or not ml_model_id:
        return
    new_id = str(uuid.uuid4())
    try:
        from sqlalchemy import text as sql_text

        async with eng.begin() as conn:
            await conn.execute(
                sql_text(
                    "INSERT INTO ml_model_invocations "
                    "(id, tenant_id, ml_model_id, execution_id, agent_id, operation, input_payload, "
                    "output, predicted_class, confidence, duration_ms, is_error, error_message, "
                    "deployment_type, cost_usd, caller_source, created_at, updated_at) "
                    "VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:mid AS uuid), "
                    "CAST(:eid AS uuid), CAST(:agid AS uuid), :operation, "
                    "CAST(:input AS jsonb), CAST(:output AS jsonb), "
                    ":predicted_class, :confidence, :duration_ms, :is_error, :error_message, "
                    ":deployment_type, :cost_usd, :caller_source, NOW(), NOW())"
                ),
                {
                    "id": new_id,
                    "tid": str(tenant_id),
                    "mid": str(ml_model_id),
                    "eid": str(execution_id) if execution_id else None,
                    "agid": str(agent_id) if agent_id else None,
                    "operation": operation or "predict",
                    "input": (
                        json.dumps(_truncate_json(input_payload), default=str)
                        if input_payload is not None
                        else None
                    ),
                    "output": (
                        json.dumps(_truncate_json(output), default=str)
                        if output is not None
                        else None
                    ),
                    "predicted_class": (
                        (predicted_class or "")[:255] if predicted_class else None
                    ),
                    "confidence": confidence,
                    "duration_ms": duration_ms,
                    "is_error": bool(is_error),
                    "error_message": _truncate_text(error_message),
                    "deployment_type": deployment_type,
                    "cost_usd": cost_usd,
                    "caller_source": caller_source,
                },
            )
    except Exception as e:
        logger.debug("invocation_log.ml_model insert failed: %s", e)
    finally:
        try:
            await eng.dispose()
        except Exception:
            pass

    try:
        await _publish_event(
            "ml_model",
            str(ml_model_id),
            {
                "id": new_id,
                "ml_model_id": str(ml_model_id),
                "agent_id": agent_id,
                "execution_id": execution_id,
                "operation": operation or "predict",
                "duration_ms": duration_ms,
                "is_error": bool(is_error),
                "predicted_class": predicted_class,
                "confidence": confidence,
                "deployment_type": deployment_type,
                "cost_usd": cost_usd,
                "error_message": _truncate_text(error_message),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
    except Exception:
        pass


async def record_kb_query(
    *,
    tenant_id: str | None,
    kb_collection_id: str | None,
    execution_id: str | None,
    agent_id: str | None,
    query_text: str | None,
    search_mode: str | None,
    top_k: int | None,
    results: Any,
    hit_count: int | None,
    duration_ms: int | None,
    is_error: bool,
    error_message: str | None,
    caller_source: str | None = "agent_runtime",
) -> None:
    try:
        from engine import metrics

        status = "error" if is_error else "ok"
        metrics.KB_QUERY_INVOCATIONS_TOTAL.labels(
            kb_collection_id=str(kb_collection_id) if kb_collection_id else "any",
            status=status,
        ).inc()
        if duration_ms is not None:
            metrics.KB_QUERY_DURATION_SECONDS.labels(
                kb_collection_id=str(kb_collection_id) if kb_collection_id else "any",
            ).observe(duration_ms / 1000.0)
    except Exception:
        pass

    eng = await _engine()
    if eng is None or not tenant_id:
        return
    new_id = str(uuid.uuid4())
    try:
        from sqlalchemy import text as sql_text

        async with eng.begin() as conn:
            await conn.execute(
                sql_text(
                    "INSERT INTO kb_query_invocations "
                    "(id, tenant_id, kb_collection_id, execution_id, agent_id, query_text, "
                    "search_mode, top_k, results, hit_count, duration_ms, is_error, "
                    "error_message, caller_source, created_at, updated_at) "
                    "VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:kid AS uuid), "
                    "CAST(:eid AS uuid), CAST(:agid AS uuid), :query_text, :search_mode, :top_k, "
                    "CAST(:results AS jsonb), :hit_count, :duration_ms, :is_error, :error_message, "
                    ":caller_source, NOW(), NOW())"
                ),
                {
                    "id": new_id,
                    "tid": str(tenant_id),
                    "kid": str(kb_collection_id) if kb_collection_id else None,
                    "eid": str(execution_id) if execution_id else None,
                    "agid": str(agent_id) if agent_id else None,
                    "query_text": _truncate_text(query_text),
                    "search_mode": search_mode,
                    "top_k": top_k,
                    "results": (
                        json.dumps(_truncate_json(results), default=str)
                        if results is not None
                        else None
                    ),
                    "hit_count": hit_count,
                    "duration_ms": duration_ms,
                    "is_error": bool(is_error),
                    "error_message": _truncate_text(error_message),
                    "caller_source": caller_source,
                },
            )
    except Exception as e:
        logger.debug("invocation_log.kb_query insert failed: %s", e)
    finally:
        try:
            await eng.dispose()
        except Exception:
            pass

    try:
        await _publish_event(
            "kb_query",
            str(kb_collection_id) if kb_collection_id else "any",
            {
                "id": new_id,
                "kb_collection_id": str(kb_collection_id) if kb_collection_id else None,
                "agent_id": agent_id,
                "execution_id": execution_id,
                "query_text": _truncate_text(query_text),
                "search_mode": search_mode,
                "hit_count": hit_count,
                "duration_ms": duration_ms,
                "is_error": bool(is_error),
                "error_message": _truncate_text(error_message),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
    except Exception:
        pass


def fire_and_forget(coro):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception:
            pass
