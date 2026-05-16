"""Backfill code_asset / ml_model / kb_query invocation rows from historical executions.tool_calls.

Idempotent: re-runs skip rows that already exist (by execution_id + resource_id +
tool_call sequence). Caller_source='backfill' marks the synthetic rows so they
can be distinguished from real-time hooks.

Usage:
    BACKFILL_DAYS=30 python scripts/backfill_resource_invocations.py

Tune BACKFILL_DAYS via env (default 30). Run via:
    kubectl exec -n abenix <api-pod> -- python /app/scripts/backfill_resource_invocations.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/packages/db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "db"))

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.execution import Execution
from models.ml_model import MLModel
from models.code_asset import CodeAsset

BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", "30"))
BATCH_SIZE = int(os.environ.get("BACKFILL_BATCH", "500"))
MAX_PAYLOAD_CHARS = 8000
UUID_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.I)


def _truncate(value):
    if value is None:
        return None
    try:
        s = json.dumps(value, default=str)
    except Exception:
        return {"_unserialisable": True}
    if len(s) <= MAX_PAYLOAD_CHARS:
        return value
    return {"_truncated": True, "preview": s[:MAX_PAYLOAD_CHARS]}


async def resolve_code_asset_id(db, tenant_id, ident):
    if not ident:
        return None
    s = str(ident).strip()
    if UUID_RE.match(s):
        return s
    row = (await db.execute(
        select(CodeAsset.id).where(
            CodeAsset.tenant_id == tenant_id,
            CodeAsset.name == s,
        )
    )).scalar_one_or_none()
    return str(row) if row else None


async def resolve_ml_model_id(db, tenant_id, name):
    if not name:
        return None
    row = (await db.execute(
        select(MLModel.id).where(
            MLModel.tenant_id == tenant_id,
            MLModel.name == str(name),
        )
    )).scalar_one_or_none()
    return str(row) if row else None


async def _exists_code_asset(db, execution_id, code_asset_id, seq):
    res = await db.execute(
        sql_text(
            "SELECT 1 FROM code_asset_invocations "
            "WHERE execution_id = CAST(:eid AS uuid) "
            "AND code_asset_id = CAST(:cid AS uuid) "
            "AND caller_source = 'backfill' LIMIT 1"
        ),
        {"eid": execution_id, "cid": code_asset_id},
    )
    return res.first() is not None


async def _insert_code_asset(db, ex, args, output, started_at, completed_at, duration_ms, is_error, err_msg, asset_id):
    await db.execute(
        sql_text(
            "INSERT INTO code_asset_invocations "
            "(id, tenant_id, code_asset_id, execution_id, agent_id, input_payload, output, "
            "duration_ms, is_error, error_message, caller_source, started_at, completed_at, "
            "created_at, updated_at) "
            "VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:aid AS uuid), "
            "CAST(:eid AS uuid), CAST(:agid AS uuid), CAST(:input AS jsonb), CAST(:output AS jsonb), "
            ":dur, :err, :msg, 'backfill', :sat, :cat, :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": str(ex.tenant_id),
            "aid": asset_id,
            "eid": str(ex.id),
            "agid": str(ex.agent_id) if ex.agent_id else None,
            "input": json.dumps(_truncate(args), default=str) if args is not None else None,
            "output": json.dumps(_truncate(output), default=str) if output is not None else None,
            "dur": duration_ms,
            "err": bool(is_error),
            "msg": err_msg,
            "sat": started_at,
            "cat": completed_at,
            "created": ex.created_at,
        },
    )


async def _exists_ml_model(db, execution_id, model_id):
    res = await db.execute(
        sql_text(
            "SELECT 1 FROM ml_model_invocations "
            "WHERE execution_id = CAST(:eid AS uuid) "
            "AND ml_model_id = CAST(:mid AS uuid) "
            "AND caller_source = 'backfill' LIMIT 1"
        ),
        {"eid": execution_id, "mid": model_id},
    )
    return res.first() is not None


async def _insert_ml_model(db, ex, args, output, duration_ms, is_error, err_msg, model_id):
    operation = (args.get("operation") if isinstance(args, dict) else None) or "predict"
    predicted_class = None
    confidence = None
    if isinstance(output, dict):
        pred = output.get("prediction") or output.get("predicted_class")
        if isinstance(pred, (str, int, float)):
            predicted_class = str(pred)[:255]
        conf = output.get("confidence") or output.get("probability")
        if isinstance(conf, (int, float)):
            confidence = float(conf)
    await db.execute(
        sql_text(
            "INSERT INTO ml_model_invocations "
            "(id, tenant_id, ml_model_id, execution_id, agent_id, operation, input_payload, output, "
            "predicted_class, confidence, duration_ms, is_error, error_message, caller_source, "
            "created_at, updated_at) "
            "VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:mid AS uuid), "
            "CAST(:eid AS uuid), CAST(:agid AS uuid), :op, "
            "CAST(:input AS jsonb), CAST(:output AS jsonb), "
            ":pc, :conf, :dur, :err, :msg, 'backfill', :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": str(ex.tenant_id),
            "mid": model_id,
            "eid": str(ex.id),
            "agid": str(ex.agent_id) if ex.agent_id else None,
            "op": operation,
            "input": json.dumps(_truncate(args), default=str) if args is not None else None,
            "output": json.dumps(_truncate(output), default=str) if output is not None else None,
            "pc": predicted_class,
            "conf": confidence,
            "dur": duration_ms,
            "err": bool(is_error),
            "msg": err_msg,
            "created": ex.created_at,
        },
    )


async def _insert_kb_query(db, ex, args, output, duration_ms, is_error, err_msg):
    query_text = (args.get("query") if isinstance(args, dict) else None) or ""
    search_mode = (args.get("mode") or args.get("search_mode")) if isinstance(args, dict) else None
    top_k = args.get("top_k") if isinstance(args, dict) else None
    collection_id = None
    if isinstance(args, dict):
        cid = args.get("collection_id") or args.get("kb_collection_id")
        if cid and UUID_RE.match(str(cid)):
            collection_id = str(cid)
    hit_count = None
    if isinstance(output, dict):
        results = output.get("results") or output.get("hits") or output.get("documents")
        if isinstance(results, list):
            hit_count = len(results)
    await db.execute(
        sql_text(
            "INSERT INTO kb_query_invocations "
            "(id, tenant_id, kb_collection_id, execution_id, agent_id, query_text, "
            "search_mode, top_k, results, hit_count, duration_ms, is_error, "
            "error_message, caller_source, created_at, updated_at) "
            "VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:kid AS uuid), "
            "CAST(:eid AS uuid), CAST(:agid AS uuid), :qt, :sm, :tk, "
            "CAST(:results AS jsonb), :hc, :dur, :err, :msg, 'backfill', :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": str(ex.tenant_id),
            "kid": collection_id,
            "eid": str(ex.id),
            "agid": str(ex.agent_id) if ex.agent_id else None,
            "qt": str(query_text)[:4000] if query_text else None,
            "sm": str(search_mode)[:32] if search_mode else None,
            "tk": int(top_k) if isinstance(top_k, int) else None,
            "results": json.dumps(_truncate(output), default=str) if output is not None else None,
            "hc": hit_count,
            "dur": duration_ms,
            "err": bool(is_error),
            "msg": err_msg,
            "created": ex.created_at,
        },
    )


async def main():
    db_url = os.environ["DATABASE_URL"]
    eng = create_async_engine(db_url, pool_pre_ping=True)
    sf = async_sessionmaker(eng, expire_on_commit=False)
    since = datetime.now(timezone.utc) - timedelta(days=BACKFILL_DAYS)
    stats = {"code_asset": 0, "ml_model": 0, "kb_query": 0, "skipped_resource": 0, "skipped_existing": 0, "executions": 0}
    print(f"backfill: scanning executions since {since.isoformat()} (BACKFILL_DAYS={BACKFILL_DAYS})")

    async with sf() as db:
        offset = 0
        while True:
            execs = (await db.execute(
                select(Execution)
                .where(Execution.created_at >= since)
                .order_by(Execution.created_at)
                .offset(offset)
                .limit(BATCH_SIZE)
            )).scalars().all()
            if not execs:
                break
            for ex in execs:
                stats["executions"] += 1
                tcs = ex.tool_calls or []
                if not isinstance(tcs, list):
                    continue
                for seq, tc in enumerate(tcs):
                    if not isinstance(tc, dict):
                        continue
                    name = tc.get("name") or tc.get("tool_name") or ""
                    args = tc.get("arguments") or tc.get("args") or {}
                    output = tc.get("result") or tc.get("output")
                    err_field = tc.get("error")
                    is_error = bool(err_field) or bool(tc.get("is_error"))
                    err_msg = str(err_field)[:2000] if isinstance(err_field, str) else None
                    duration_ms = tc.get("duration_ms")
                    started_at = tc.get("started_at")
                    completed_at = tc.get("completed_at")
                    try:
                        if name == "code_asset":
                            aid = await resolve_code_asset_id(db, ex.tenant_id, args.get("code_asset_id") if isinstance(args, dict) else None)
                            if not aid:
                                stats["skipped_resource"] += 1
                                continue
                            if await _exists_code_asset(db, str(ex.id), aid, seq):
                                stats["skipped_existing"] += 1
                                continue
                            await _insert_code_asset(db, ex, args, output, started_at, completed_at, duration_ms, is_error, err_msg, aid)
                            stats["code_asset"] += 1
                        elif name == "ml_model":
                            mname = args.get("model_name") if isinstance(args, dict) else None
                            mid = await resolve_ml_model_id(db, ex.tenant_id, mname)
                            if not mid:
                                stats["skipped_resource"] += 1
                                continue
                            if await _exists_ml_model(db, str(ex.id), mid):
                                stats["skipped_existing"] += 1
                                continue
                            await _insert_ml_model(db, ex, args, output, duration_ms, is_error, err_msg, mid)
                            stats["ml_model"] += 1
                        elif name in ("knowledge_search", "kb_query"):
                            await _insert_kb_query(db, ex, args, output, duration_ms, is_error, err_msg)
                            stats["kb_query"] += 1
                    except Exception as e:
                        print(f"  skip exec={ex.id} seq={seq} name={name}: {e}", flush=True)
                        stats["skipped_existing"] += 1
                await db.commit()
            offset += BATCH_SIZE
            print(f"  checkpoint offset={offset} stats={stats}", flush=True)
    await eng.dispose()
    print("=" * 60)
    print(f"DONE: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
