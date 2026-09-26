"""Wave-2 per-pool consumer — pulls agent-execution jobs off the queue"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent-runtime.consumer")
logging.basicConfig(
    # Python's logging.basicConfig needs an uppercase level name or an
    # int. Helm/K8s idiomatically set lowercase ("info") — normalise so
    # we don't crash on boot.
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
# Make the shared packages importable the same way the API does
sys.path.insert(0, str(_REPO / "apps" / "api"))
sys.path.insert(0, str(_REPO / "packages" / "db"))
sys.path.insert(0, str(_HERE))


_engine = None
_session_factory = None
_engine_lock = asyncio.Lock()


async def _get_session_factory():
    global _engine, _session_factory
    if _session_factory is not None:
        return _session_factory
    async with _engine_lock:
        if _session_factory is not None:
            return _session_factory
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        db_url = os.environ.get("DATABASE_URL") or os.environ.get(
            "DATABASE_URL_ASYNC",
            "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
        )
        pool_size = int(os.environ.get("CONSUMER_DB_POOL_SIZE", "10"))
        max_overflow = int(os.environ.get("CONSUMER_DB_MAX_OVERFLOW", "5"))
        _engine = create_async_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=3600,
        )
        _session_factory = sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        return _session_factory


async def _load_execution(execution_id: str) -> dict[str, Any] | None:
    from sqlalchemy import select

    from models.agent import Agent  # type: ignore
    from models.execution import Execution  # type: ignore

    Session = await _get_session_factory()
    async with Session() as db:
        res = await db.execute(
            select(Execution).where(Execution.id == uuid.UUID(execution_id))
        )
        execution = res.scalar_one_or_none()
        if execution is None:
            return None
        res = await db.execute(select(Agent).where(Agent.id == execution.agent_id))
        agent = res.scalar_one_or_none()
        if agent is None:
            return None
        model_cfg = agent.model_config_ or {}
        kb_ids: list[str] = []
        try:
            from sqlalchemy import select as _select

            from models.agent_collection_grant import AgentCollectionGrant  # type: ignore

            allowed = {"read", "write", "admin"}
            grants = await db.execute(
                _select(AgentCollectionGrant.collection_id).where(
                    AgentCollectionGrant.agent_id == agent.id,
                    AgentCollectionGrant.permission.in_(allowed),
                )
            )
            kb_ids = [str(row[0]) for row in grants.all()]
        except Exception:
            kb_ids = []
        return {
            "execution": execution,
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            # slug drives the per-agent post-processor lookup; without it
            # the canonical-anchor guardrail can't bind to fairvalue runs.
            "agent_slug": getattr(agent, "slug", "") or "",
            "agent_status": getattr(agent, "status", None),
            "is_pipeline": model_cfg.get("mode") == "pipeline",
            "model_cfg": model_cfg,
            "system_prompt": agent.system_prompt or "",
            "tool_names": model_cfg.get("tools", []) or [],
            "pipeline_config": model_cfg.get("pipeline_config"),
            "tenant_id": str(execution.tenant_id),
            "kb_ids": kb_ids,
        }


async def _load_moderation_gate(
    tenant_id: str,
) -> Any:
    """Build a GateConfig for the tenant's active moderation policy.

    Queue-routed runs don't pass through the API-side build_gate_context
    helper, so the consumer recreates the same shape here. Returns None
    when there's no active policy (gate-off path stays a no-op).
    """
    try:
        from sqlalchemy import desc, select

        from engine.moderation_gate import GateConfig
        from models.moderation_policy import (  # type: ignore
            ModerationAction,
            ModerationPolicy,
        )
    except Exception:
        return None
    try:
        Session = await _get_session_factory()
        async with Session() as db:
            res = await db.execute(
                select(ModerationPolicy)
                .where(ModerationPolicy.tenant_id == uuid.UUID(tenant_id))
                .where(ModerationPolicy.is_active.is_(True))
                .order_by(desc(ModerationPolicy.updated_at))
                .limit(1)
            )
            policy = res.scalars().first()
            if policy is None:
                return None
            return GateConfig(
                policy_id=str(policy.id),
                tenant_id=str(policy.tenant_id),
                user_id="",
                pre_llm=bool(policy.pre_llm),
                post_llm=bool(policy.post_llm),
                on_tool_output=bool(policy.on_tool_output),
                provider_model=str(policy.provider_model or "omni-moderation-latest"),
                thresholds=dict(policy.thresholds or {}),
                default_threshold=float(policy.default_threshold),
                category_actions=dict(policy.category_actions or {}),
                default_action=(
                    policy.default_action.value
                    if isinstance(policy.default_action, ModerationAction)
                    else str(policy.default_action)
                ),
                custom_patterns=list(policy.custom_patterns or []),
                redaction_mask=str(policy.redaction_mask or "█████"),
                fail_closed=bool(getattr(policy, "fail_closed", False)),
                event_sink=None,
            )
    except Exception as e:
        logger.warning("could not load moderation gate for tenant %s: %s", tenant_id, e)
        return None


async def _update_usage_counters(
    api_key_id: str | None,
    user_id: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost: float | None,
) -> None:
    """Debit api_keys + users monthly counters after a queue-routed run.

    Mirrors the inline path's app.core.usage.update_user_usage so customer
    quotas stay enforced when the API hands the execution off to NATS/Redis.
    Best-effort: a usage-write failure must never break the execution.
    """
    if not api_key_id and not user_id:
        return
    total_tokens = int((input_tokens or 0) + (output_tokens or 0))
    cost_delta = float(cost or 0)
    if total_tokens == 0 and cost_delta == 0:
        return
    try:
        from sqlalchemy import text

        Session = await _get_session_factory()
        async with Session() as side:
            if api_key_id:
                await side.execute(
                    text(
                        "UPDATE api_keys SET tokens_used = COALESCE(tokens_used, 0) + :n, "
                        "cost_used = COALESCE(cost_used, 0) + :c WHERE id = :id"
                    ),
                    {"n": total_tokens, "c": cost_delta, "id": uuid.UUID(api_key_id)},
                )
            if user_id:
                await side.execute(
                    text(
                        "UPDATE users SET tokens_used_this_month = COALESCE(tokens_used_this_month, 0) + :n, "
                        "cost_used_this_month = COALESCE(cost_used_this_month, 0) + :c WHERE id = :uid"
                    ),
                    {"n": total_tokens, "c": cost_delta, "uid": uuid.UUID(user_id)},
                )
            await side.commit()
    except Exception as _ue:
        logger.warning("consumer: usage counter update skipped for execution: %s", _ue)


async def _mark_started(execution_id: str) -> None:
    """Stamp started_at when the consumer picks up the row. No-op if already set."""
    from datetime import datetime, timezone
    from sqlalchemy import update
    from models.execution import Execution  # type: ignore

    Session = await _get_session_factory()
    async with Session() as db:
        await db.execute(
            update(Execution)
            .where(Execution.id == uuid.UUID(execution_id))
            .where(Execution.started_at.is_(None))
            .values(started_at=datetime.now(timezone.utc))
        )
        await db.commit()


async def _mark_done(
    execution_id: str,
    status: str,
    output: str | None,
    error: str | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost: float | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
    node_results: dict[str, Any] | None = None,
    execution_trace: dict[str, Any] | list[Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from models.execution import Execution, ExecutionStatus  # type: ignore

    Session = await _get_session_factory()

    target_status = (
        ExecutionStatus.COMPLETED if status == "completed" else ExecutionStatus.FAILED
    )
    completed_at = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "status": target_status,
        "output_message": output,
        "error_message": error,
        "completed_at": completed_at,
    }
    if input_tokens is not None:
        values["input_tokens"] = input_tokens
    if output_tokens is not None:
        values["output_tokens"] = output_tokens
    # Write a known cost even when zero — skipping 0.0 left the column NULL,
    # which reads as "never recorded" rather than "free".
    if cost is not None:
        values["cost"] = round(float(cost), 6)
    if tool_calls is not None:
        values["tool_calls"] = tool_calls
    if node_results is not None:
        values["node_results"] = node_results
    if execution_trace is not None:
        values["execution_trace"] = execution_trace
    if duration_ms is not None:
        values["duration_ms"] = duration_ms
    if trace_id:
        values["trace_id"] = trace_id
    else:
        try:
            from engine.tracing import current_trace_id

            _tid = current_trace_id()
            if _tid:
                values["trace_id"] = _tid
        except Exception:
            pass
    # On failure, classify the error_message into a stable failure_code so
    # /alerts can group it and the Surgeon has something to act on.
    if target_status == ExecutionStatus.FAILED and error:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
            from app.core.failure_codes import classify_exception  # type: ignore

            values["failure_code"] = classify_exception(Exception(error))
        except Exception:
            # Fallback: a generic code so /alerts at least groups by something.
            values["failure_code"] = "PIPELINE_NODE_FAILED"
    async with Session() as db:
        # Backfill started_at + derive duration_ms when the runtime didn't
        # supply one. Without this, /executions surfaces null duration_ms
        # for every row this consumer touched.
        row = (
            await db.execute(
                select(Execution.started_at, Execution.created_at).where(
                    Execution.id == uuid.UUID(execution_id)
                )
            )
        ).one_or_none()
        if row is not None:
            started_at, created_at = row
            if started_at is None:
                started_at = created_at or completed_at
                values["started_at"] = started_at
            if "duration_ms" not in values and started_at is not None:
                values["duration_ms"] = int(
                    (completed_at - started_at).total_seconds() * 1000
                )
        await db.execute(
            update(Execution)
            .where(Execution.id == uuid.UUID(execution_id))
            .values(**values)
        )
        await db.commit()


_redis_pool: Any = None


def _emit_outcome(
    *,
    outcome: str,
    failure_code: str = "",
    agent_type: str = "agent",
    tenant_id: str = "",
) -> None:
    """Forward the runtime-side terminal outcome to the same Prometheus
    counters the API path emits to. Without this, executions that ran
    out-of-process (Wave-2 remote runtime) never hit
    executions_completed_total / executions_failed_total and never
    decremented active_executions, leaving both counters dead and the
    gauge drifting up by N for every runtime-completed run."""
    try:
        from app.core.failure_codes import emit_outcome_metric  # type: ignore

        emit_outcome_metric(
            outcome=outcome,
            failure_code=failure_code,
            agent_type=agent_type,
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.warning("consumer _emit_outcome failed: %s", e)


async def _publish(execution_id: str, event: dict) -> None:
    """Fire an event onto Redis pub/sub + append to the bounded replay log"""
    global _redis_pool
    try:
        import redis.asyncio as aioredis
        import json as _json

        if _redis_pool is None:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            _redis_pool = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        payload = _json.dumps(event, default=str)
        channel = f"exec:events:{execution_id}"
        log_key = f"{channel}:log"
        pipe = _redis_pool.pipeline()
        pipe.publish(channel, payload)
        pipe.rpush(log_key, payload)
        pipe.ltrim(log_key, -500, -1)
        pipe.expire(log_key, 3600)
        await pipe.execute()
    except Exception as e:
        logger.debug("execution_bus.publish failed: %s", e)


async def _run_one(payload: dict) -> None:
    """Run a single execution. Publishes start/node/done/error events."""
    execution_id = payload.get("execution_id")
    if not execution_id:
        logger.error("consumer: payload missing execution_id: %s", payload)
        return

    message = payload.get("message", "")
    context = payload.get("context") or {}
    api_key_id = payload.get("api_key_id") or None
    user_id = payload.get("user_id") or None

    loaded = await _load_execution(execution_id)
    if loaded is None:
        logger.warning("consumer: execution %s not found; skipping", execution_id)
        await _publish(
            execution_id, {"event": "error", "error": "execution row missing"}
        )
        return

    # First real work on this row — stamp started_at so duration_ms can be
    # computed at _mark_done time. No-op if the API path already stamped it.
    try:
        await _mark_started(execution_id)
    except Exception as _ms_err:
        logger.debug("consumer: _mark_started failed: %s", _ms_err)

    agent_name = loaded["agent_name"]
    tenant_id = loaded["tenant_id"]
    is_pipeline = loaded["is_pipeline"]

    await _publish(
        execution_id,
        {
            "event": "start",
            "execution_id": execution_id,
            "agent": agent_name,
            "pool": os.environ.get("RUNTIME_POOL", "default"),
            "mode": "pipeline" if is_pipeline else "agent",
        },
    )

    try:
        if is_pipeline:
            from engine.pipeline import (
                PipelineExecutor,
                parse_pipeline_nodes,
                serialize_pipeline_result,
            )
            from engine.agent_executor import build_tool_registry

            async def on_node_start(node_id: str, tool_name: str) -> None:
                await _publish(
                    execution_id,
                    {
                        "event": "node_start",
                        "node_id": node_id,
                        "tool_name": tool_name,
                    },
                )

            async def on_node_complete(
                node_id: str,
                status: str,
                duration_ms: int,
                output: Any,
                error_message: str | None = None,
                error_type: str | None = None,
            ) -> None:
                evt: dict[str, Any] = {
                    "event": "node_complete",
                    "node_id": node_id,
                    "status": status,
                    "duration_ms": duration_ms,
                }
                if status == "failed" and error_message:
                    evt["error"] = error_message[:2000]
                    if error_type:
                        evt["error_type"] = error_type
                elif output is not None:
                    out_text = str(output) if not isinstance(output, str) else output
                    evt["output_preview"] = out_text[:500]
                    # Provenance: surface the top-level JSON keys this node
                    # produced so the OracleNet provenance tab can render
                    # real lineage instead of static layout. Best-effort —
                    # if output isn't JSON we just skip the field map.
                    try:
                        from engine.post_process import _extract_json  # type: ignore

                        parsed = (
                            output
                            if isinstance(output, dict)
                            else _extract_json(out_text)
                        )
                        if isinstance(parsed, dict):
                            evt["produced_fields"] = sorted(list(parsed.keys()))[:50]
                    except Exception:
                        pass
                await _publish(execution_id, evt)

            pipeline_config = loaded["pipeline_config"] or {}
            raw_nodes = pipeline_config.get("nodes", [])
            nodes = parse_pipeline_nodes(raw_nodes)
            for node in nodes:
                if node.tool_name == "web_search" and "query" not in node.arguments:
                    node.arguments["query"] = message

            registry = build_tool_registry(
                loaded["tool_names"],
                agent_id=loaded.get("agent_id"),
                tenant_id=loaded.get("tenant_id"),
                kb_ids=loaded.get("kb_ids") or [],
            )
            executor = PipelineExecutor(
                tool_registry=registry,
                timeout_seconds=120,
                on_node_start=on_node_start,
                on_node_complete=on_node_complete,
                agent_id=loaded["agent_id"],
                tenant_id=tenant_id,
                db_url=os.environ.get("DATABASE_URL", ""),
            )
            # Inject execution_id into context so the executor's healing
            # capture path can attribute the diff back to this run.
            result = await executor.execute(
                nodes,
                {"user_message": message, "__execution_id": execution_id, **context},
            )
            serialized = serialize_pipeline_result(result)
            final_text = ""
            # Generic post-process for pipeline final_output: same logic as
            # the agent path. Drives OracleNet's strict-enum guarantees.
            _pipeline_warnings: list[str] = []
            try:
                _output_schema = (loaded.get("model_cfg") or {}).get("output_schema")
                if _output_schema and result.final_output is not None:
                    from engine.post_process import post_process  # type: ignore

                    _normalized, _pipeline_warnings = post_process(
                        result.final_output, _output_schema
                    )
                    if isinstance(_normalized, (dict, list)):
                        result.final_output = _normalized
                    if _pipeline_warnings:
                        logger.info(
                            "pipeline post_process: %s warnings",
                            len(_pipeline_warnings),
                        )
            except Exception as _e:
                logger.warning("pipeline post_process skipped: %s", _e)

            if result.final_output:
                # 50 KB cap matches the DB output_message column.
                final_text = (
                    result.final_output
                    if isinstance(result.final_output, str)
                    else json.dumps(result.final_output, default=str)[:50_000]
                )

            # Translate the executor's status to the DB row's status.
            # Without this, every pipeline run shows status=completed even
            # when one or more nodes failed — masking real failures from
            # /executions, /alerts, and the Surgeon's failure-diff capture.
            pipeline_status = "completed" if result.status == "completed" else "failed"
            failed_nodes = serialized.get("failed_nodes") or []
            err_text = None
            if pipeline_status == "failed":
                node_errs = []
                for nid, nr in (serialized.get("node_results") or {}).items():
                    if (nr.get("status") == "failed") and nr.get("error"):
                        node_errs.append(f"{nid}: {nr['error']}")
                err_text = (
                    "; ".join(node_errs) or f"failed nodes: {','.join(failed_nodes)}"
                )[:2000]

            await _mark_done(
                execution_id,
                pipeline_status,
                final_text,
                err_text,
                node_results=serialized.get("node_results"),
                execution_trace=serialized,
                duration_ms=serialized.get("duration_ms"),
            )
            # Debit api_keys / users so customer quotas stay enforced on
            # queue-routed pipeline runs. Pipelines aggregate token counts
            # on the result object the same way agent runs do.
            if pipeline_status == "completed":
                _pipe_in = int(getattr(result, "input_tokens", 0) or 0)
                _pipe_out = int(getattr(result, "output_tokens", 0) or 0)
                _pipe_cost = float(getattr(result, "cost", 0.0) or 0.0)
                await _update_usage_counters(
                    api_key_id, user_id, _pipe_in, _pipe_out, _pipe_cost
                )
            _emit_outcome(
                outcome="SUCCESS" if pipeline_status == "completed" else "FAILED",
                failure_code=(
                    "" if pipeline_status == "completed" else "PIPELINE_NODE_FAILED"
                ),
                agent_type="pipeline",
                tenant_id=str(tenant_id) if tenant_id else "",
            )
            _pipe_evt: dict[str, Any] = {
                "event": "done" if pipeline_status == "completed" else "error",
                "execution_id": execution_id,
                "output": final_text,
                "summary": serialized,
            }
            if err_text:
                _pipe_evt["error"] = err_text
            if _pipeline_warnings:
                _pipe_evt["validation_warnings"] = _pipeline_warnings[:20]
            await _publish(execution_id, _pipe_evt)
        else:
            from engine.agent_executor import (
                AgentExecutor,
                build_tool_registry,
                resolve_asset_schemas,
            )
            from engine.llm_router import LLMRouter

            registry = build_tool_registry(
                loaded["tool_names"],
                agent_id=loaded["agent_id"],
                tenant_id=tenant_id,
                execution_id=execution_id,
                agent_name=agent_name,
                db_url=os.environ.get("DATABASE_URL", ""),
                model_config=loaded.get("model_cfg") or {},
                kb_ids=loaded.get("kb_ids") or [],
            )
            llm_router = LLMRouter()
            _tool_cfg = loaded["model_cfg"].get("tool_config") or {}
            _asset_schemas = await resolve_asset_schemas(_tool_cfg)
            # Pull the grounded-response contract and the moderation gate
            # for queue-routed runs too. Without this, RUNTIME_MODE=remote
            # plus QUEUE_BACKEND=nats silently bypassed both controls.
            _require_kb = bool(
                loaded["model_cfg"].get("require_knowledge_search", False)
            )
            _moderation_gate = await _load_moderation_gate(tenant_id)
            executor = AgentExecutor(
                llm_router=llm_router,
                tool_registry=registry,
                system_prompt=loaded["system_prompt"],
                model=loaded["model_cfg"].get("model", "claude-sonnet-4-5-20250929"),
                temperature=loaded["model_cfg"].get("temperature", 0.7),
                max_iterations=loaded["model_cfg"].get("max_iterations", 10),
                max_tokens=loaded["model_cfg"].get("max_tokens", 4096),
                agent_id=loaded["agent_id"],
                execution_id=execution_id,
                tenant_id=str(loaded.get("tenant_id") or ""),
                # Apply tool-schema injection here too so the NATS
                # consumer path behaves the same as the inline path.
                tool_config=_tool_cfg,
                asset_schemas=_asset_schemas,
                require_knowledge_search=_require_kb,
                moderation_gate=_moderation_gate,
            )
            # Stream so per-iteration events reach Redis pub/sub live; invoke() only emits start+done.
            from types import SimpleNamespace

            _full_text_parts: list[str] = []
            _agg_tool_calls: list[dict[str, Any]] = []
            # _tool_runs pairs each tool invocation with a compact summary of
            # its result (status, metadata, etc) so per-agent post-processors
            # can recompute against canonical data without going back to the
            # tool. Filled from `node_trace` events, which carry the full
            # ToolResult.metadata.
            _tool_runs: list[dict[str, Any]] = []
            _last_done: dict[str, Any] = {}
            async for _ev in executor.stream(message):
                if _ev.event == "done" and isinstance(_ev.data, dict):
                    _last_done = _ev.data
                    continue
                _evt: dict[str, Any] = {"event": _ev.event}
                if isinstance(_ev.data, dict):
                    _evt.update(_ev.data)
                else:
                    _evt["data"] = _ev.data
                await _publish(execution_id, _evt)
                if _ev.event == "token" and isinstance(_ev.data, str):
                    _full_text_parts.append(_ev.data)
                elif _ev.event == "tool_call" and isinstance(_ev.data, dict):
                    _agg_tool_calls.append(_ev.data)
                    try:
                        from app.core.execution_state import append_tool_call as _append_tc  # type: ignore

                        await _append_tc(execution_id, _ev.data)
                    except Exception as _ape:
                        logger.debug("append_tool_call failed: %s", _ape)
                elif _ev.event == "node_trace" and isinstance(_ev.data, dict):
                    # node_trace fires per tool with the real result.metadata
                    # attached — exactly what the post-processor needs to
                    # reconstruct the canonical anchor. Prefer the new
                    # output_summary field; fall back to a metadata projection
                    # for compatibility with older executor builds.
                    if (_ev.data.get("node_type") or "") == "tool_call":
                        _meta = _ev.data.get("metadata") or {}
                        _summary = _ev.data.get("output_summary") or {
                            "status": (
                                "ok"
                                if not _ev.data.get("is_error")
                                and _meta.get("status", "ok") == "ok"
                                else _meta.get("status") or "error"
                            ),
                            "resolved_symbol": _meta.get("resolved_symbol")
                            or _meta.get("symbol")
                            or "",
                            "symbol": _meta.get("symbol") or "",
                            "closes": _meta.get("closes") or [],
                            "prices_count": int(
                                _meta.get("price_count")
                                or len(_meta.get("closes") or [])
                            ),
                            "latest_close": _meta.get("latest_close"),
                            "fetched_at": _meta.get("fetched_at")
                            or _meta.get("last_refresh")
                            or "",
                            "currency": _meta.get("currency") or "",
                        }
                        _tool_runs.append(
                            {
                                "tool": _ev.data.get("tool") or "",
                                "input": _ev.data.get("input") or {},
                                "output_summary": _summary,
                            }
                        )
            result = SimpleNamespace(
                output="".join(_full_text_parts),
                tool_calls=_agg_tool_calls,
                input_tokens=int(_last_done.get("input_tokens", 0)),
                output_tokens=int(_last_done.get("output_tokens", 0)),
                cost=float(_last_done.get("cost", 0.0)),
                duration_ms=int(_last_done.get("duration_ms", 0)),
                model=_last_done.get("model", loaded["model_cfg"].get("model", "")),
            )
            output = result.output or str(result)

            # Generic post-process: if the agent's model_config declares an
            # output_schema, validate + normalize obvious enum drift before
            # the result lands in the DB. Warnings ride on the SSE event so
            # the UI can render them in a "validation" affordance.
            _validation_warnings: list[str] = []
            try:
                _output_schema = (loaded.get("model_cfg") or {}).get("output_schema")
                if _output_schema:
                    from engine.post_process import post_process  # type: ignore

                    _normalized, _validation_warnings = post_process(
                        output, _output_schema
                    )
                    if _validation_warnings:
                        logger.info(
                            "post_process: %s warnings for %s",
                            len(_validation_warnings),
                            agent_name,
                        )
                    # If we successfully parsed + normalized, persist the
                    # cleaned JSON string so the UI doesn't have to do its
                    # own enum coercion.
                    if isinstance(_normalized, (dict, list)):
                        output = json.dumps(_normalized, default=str)
            except Exception as _e:
                logger.warning("consumer: post_process skipped: %s", _e)

            # Per-agent deterministic post-processor — runs AFTER the generic
            # schema walker so domain knowledge (e.g. "TTF anchor must trump
            # the agent's fabricated decay") overrides whatever the LLM said.
            # No-op for agents that haven't registered one.
            try:
                _slug = loaded.get("agent_slug") or ""
                if _slug:
                    from engine.post_processors import get as _get_pp, run as _run_pp  # type: ignore
                    from engine.post_process import _extract_json as _xj  # type: ignore

                    if _get_pp(_slug) is not None:
                        _parsed = (
                            json.loads(output)
                            if isinstance(output, str)
                            and output.strip().startswith("{")
                            else None
                        )
                        if _parsed is None and isinstance(output, str):
                            _parsed = _xj(output)
                        if isinstance(_parsed, dict):
                            _rewritten = _run_pp(_slug, _parsed, _tool_runs, output)
                            if isinstance(_rewritten, dict):
                                output = json.dumps(_rewritten, default=str)
            except Exception as _ppe:
                logger.warning("consumer: per-agent post_processor skipped: %s", _ppe)
            # 50 KB cap matches /apps/api routers/agents.py and the DB
            # Text column. Bumped from 4_000 — the old cap silently
            # truncated long synthesizer briefs (OracleNet, executive
            # briefing) and produced invalid partial JSON in the UI.
            _AGENT_OUTPUT_CAP = 50_000
            full_output_str = str(output)[:_AGENT_OUTPUT_CAP]
            _tid_done = (
                _last_done.get("trace_id") if isinstance(_last_done, dict) else None
            )
            if not _tid_done:
                _tid_done = getattr(executor, "_trace_id_for_log", None)
            _exec_trace: dict[str, Any] | None = None
            try:
                _exec_trace = {
                    "steps": (
                        executor.get_trace_summary()
                        if hasattr(executor, "get_trace_summary")
                        else []
                    ),
                    "tool_calls": _agg_tool_calls,
                }
            except Exception as _te:
                logger.debug("trace summary unavailable: %s", _te)
                _exec_trace = None
            await _mark_done(
                execution_id,
                "completed",
                full_output_str,
                None,
                input_tokens=getattr(result, "input_tokens", None),
                output_tokens=getattr(result, "output_tokens", None),
                cost=getattr(result, "cost", None),
                tool_calls=_agg_tool_calls or None,
                trace_id=_tid_done,
                execution_trace=_exec_trace,
                duration_ms=getattr(result, "duration_ms", None) or None,
            )
            # Debit api_keys / users counters — the inline path does this
            # via app.core.usage.update_user_usage; queue-routed runs need
            # the same write or customer quotas silently never enforce.
            await _update_usage_counters(
                api_key_id,
                user_id,
                int(getattr(result, "input_tokens", 0) or 0),
                int(getattr(result, "output_tokens", 0) or 0),
                float(getattr(result, "cost", 0.0) or 0.0),
            )
            _emit_outcome(
                outcome="SUCCESS",
                failure_code="",
                agent_type="agent",
                tenant_id=str(tenant_id) if tenant_id else "",
            )
            _done_evt: dict[str, Any] = {
                "event": "done",
                "execution_id": execution_id,
                "output": full_output_str,
                "input_tokens": getattr(result, "input_tokens", None),
                "output_tokens": getattr(result, "output_tokens", None),
                "cost": getattr(result, "cost", None),
            }
            if _validation_warnings:
                _done_evt["validation_warnings"] = _validation_warnings[:20]
            await _publish(execution_id, _done_evt)
    except Exception as e:
        logger.exception("consumer: execution %s failed: %s", execution_id, e)
        _tid_fail = None
        try:
            _tid_fail = getattr(executor, "_trace_id_for_log", None)  # type: ignore[name-defined]
        except Exception:
            pass
        await _mark_done(
            execution_id, "failed", None, str(e)[:2000], trace_id=_tid_fail
        )
        # Classify + emit the runtime-side terminal outcome. Without this,
        # every remote-runtime failure left active_executions stuck +1
        # and never bumped executions_failed_total.
        _failure_code = "UNKNOWN_ERROR"
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
            from app.core.failure_codes import classify_exception  # type: ignore

            _failure_code = classify_exception(e)
        except Exception:
            pass
        _emit_outcome(
            outcome="FAILED",
            failure_code=_failure_code,
            agent_type="pipeline" if is_pipeline else "agent",
            tenant_id=str(tenant_id) if tenant_id else "",
        )
        await _publish(execution_id, {"event": "error", "error": str(e)[:2000]})


async def _serve_health(port: int = 8001) -> None:
    """Tiny asyncio HTTP server on /health and /metrics."""
    # Touch engine.metrics to ensure all counters are registered in the
    # default registry before Prometheus asks for them.
    try:
        import engine.metrics  # type: ignore  # noqa: F401
    except Exception as e:
        logger.warning("engine.metrics not importable; /metrics will be empty: %s", e)
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    except Exception as e:
        logger.warning("prometheus_client unavailable; /metrics disabled: %s", e)
        generate_latest = None  # type: ignore
        CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"  # type: ignore

    async def _handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            # Drain headers
            while True:
                line = await reader.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
        except Exception:
            request_line = b""

        path = b"/health"
        try:
            parts = request_line.split(b" ")
            if len(parts) >= 2:
                path = parts[1].split(b"?")[0]
        except Exception:
            pass

        if path == b"/metrics" and generate_latest is not None:
            try:
                payload = generate_latest()
                ctype = (
                    CONTENT_TYPE_LATEST.encode()
                    if isinstance(CONTENT_TYPE_LATEST, str)
                    else CONTENT_TYPE_LATEST
                )
            except Exception as e:
                payload = f"# metrics render failed: {e}".encode()
                ctype = b"text/plain; charset=utf-8"
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: " + ctype + b"\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + payload
            )
        else:
            body = b'{"ok":true,"mode":"consumer"}'
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body
            )
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


async def main() -> None:
    mode = os.environ.get("RUNTIME_MODE", "embedded").lower()
    pool = os.environ.get("RUNTIME_POOL", "default")
    backend_name = os.environ.get("QUEUE_BACKEND", "celery").lower()

    if mode != "remote":
        logger.info("consumer: RUNTIME_MODE=%s — not a remote consumer, exiting.", mode)
        return

    try:
        from engine.tracing import init_tracing

        init_tracing(f"agent-runtime-{pool}")
    except Exception as e:
        logger.warning("consumer: tracing init failed (continuing without): %s", e)

    logger.info("consumer: starting pool=%s backend=%s", pool, backend_name)

    health_port = int(os.environ.get("HEALTH_PORT", "8001"))
    health_task = asyncio.create_task(_serve_health(health_port))

    # Keep a module-level reference to the tool_stream_consumer task so it
    # is not garbage-collected — the variable is intentionally unused
    # after assignment. Prefix with `_` so ruff F841 stays quiet.
    _tool_worker_task: asyncio.Task | None = None
    if os.environ.get("TOOL_WORKER_ENABLED", "1") == "1":
        try:
            from tool_stream_consumer import consumer_loop as _tool_consumer_loop  # type: ignore

            _tool_worker_task = asyncio.create_task(_tool_consumer_loop())
            logger.info("tool_stream_consumer task launched alongside NATS consumer")
        except Exception as e:
            logger.warning("tool_stream_consumer launch failed: %s", e)

    from engine.queue_backend import get_queue_backend  # type: ignore

    backend = get_queue_backend()

    stop = asyncio.Event()

    def _stop(*_a: Any) -> None:
        logger.info("consumer: shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except Exception:
            pass

    # Celery consumption is handled by the existing celery worker image —
    # the Wave-2 consumer is only meaningful for NATS today.
    if backend_name != "nats":
        logger.warning(
            "consumer: QUEUE_BACKEND=%s — consumer is a no-op (Celery workers "
            "consume via their own entrypoint). Exiting idle.",
            backend_name,
        )
        # Sleep forever so the pod stays alive under liveness probes.
        await stop.wait()
        return

    max_concurrency = int(
        os.environ.get("AGENT_CONCURRENCY")
        or os.environ.get("CONSUMER_MAX_CONCURRENCY")
        or "8"
    )
    concurrency_gate = asyncio.Semaphore(max_concurrency)
    in_flight: set[asyncio.Task[Any]] = set()
    logger.info("consumer: concurrency cap = %d", max_concurrency)

    async def _bounded(p: dict[str, Any]) -> None:
        async with concurrency_gate:
            try:
                await _run_one(p)
            except Exception:
                logger.exception("consumer: _run_one crashed")

    try:
        async for msg in backend.stream(pool):
            if stop.is_set():
                break
            task_id = msg.get("task_id", "?")
            payload = msg.get("payload") or msg
            await concurrency_gate.acquire()
            concurrency_gate.release()
            logger.info("consumer: picked task %s from agents.%s", task_id, pool)
            t = asyncio.create_task(_bounded(payload))
            in_flight.add(t)
            t.add_done_callback(in_flight.discard)
    except Exception as e:
        logger.exception("consumer: stream loop crashed: %s", e)
        raise
    finally:
        health_task.cancel()
        try:
            await health_task
        except (asyncio.CancelledError, Exception):
            pass


if __name__ == "__main__":
    asyncio.run(main())
