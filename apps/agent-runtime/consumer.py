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


async def _load_execution(execution_id: str) -> dict[str, Any] | None:
    """Load the agent + execution row using a fresh SQLAlchemy session."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from models.agent import Agent  # type: ignore
    from models.execution import Execution  # type: ignore

    db_url = os.environ.get("DATABASE_URL") or os.environ.get(
        "DATABASE_URL_ASYNC",
        "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
    )
    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        res = await db.execute(select(Execution).where(Execution.id == uuid.UUID(execution_id)))
        execution = res.scalar_one_or_none()
        if execution is None:
            return None
        res = await db.execute(select(Agent).where(Agent.id == execution.agent_id))
        agent = res.scalar_one_or_none()
        if agent is None:
            return None
        model_cfg = agent.model_config_ or {}
        return {
            "execution": execution,
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "agent_status": getattr(agent, "status", None),
            "is_pipeline": model_cfg.get("mode") == "pipeline",
            "model_cfg": model_cfg,
            "system_prompt": agent.system_prompt or "",
            "tool_names": model_cfg.get("tools", []) or [],
            "pipeline_config": model_cfg.get("pipeline_config"),
            "tenant_id": str(execution.tenant_id),
        }


async def _mark_done(
    execution_id: str,
    status: str,
    output: str | None,
    error: str | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost: float | None = None,
) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from models.execution import Execution, ExecutionStatus  # type: ignore

    db_url = os.environ.get("DATABASE_URL") or os.environ.get(
        "DATABASE_URL_ASYNC",
        "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix",
    )
    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    target_status = ExecutionStatus.COMPLETED if status == "completed" else ExecutionStatus.FAILED
    values: dict[str, Any] = {
        "status": target_status,
        "output_message": output,
        "error_message": error,
        "completed_at": datetime.now(timezone.utc),
    }
    if input_tokens is not None:  values["input_tokens"]  = input_tokens
    if output_tokens is not None: values["output_tokens"] = output_tokens
    if cost is not None and cost > 0: values["cost"] = round(float(cost), 6)
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
        await db.execute(
            update(Execution)
            .where(Execution.id == uuid.UUID(execution_id))
            .values(**values)
        )
        await db.commit()


_redis_pool: Any = None

async def _publish(execution_id: str, event: dict) -> None:
    """Fire an event onto Redis pub/sub + append to the bounded replay log"""
    global _redis_pool
    try:
        import redis.asyncio as aioredis
        import json as _json
        if _redis_pool is None:
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            _redis_pool = aioredis.from_url(
                redis_url, decode_responses=True,
                socket_connect_timeout=3, socket_timeout=3,
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

    loaded = await _load_execution(execution_id)
    if loaded is None:
        logger.warning("consumer: execution %s not found; skipping", execution_id)
        await _publish(execution_id, {"event": "error", "error": "execution row missing"})
        return

    agent_name = loaded["agent_name"]
    tenant_id = loaded["tenant_id"]
    is_pipeline = loaded["is_pipeline"]

    await _publish(execution_id, {
        "event": "start",
        "execution_id": execution_id,
        "agent": agent_name,
        "pool": os.environ.get("RUNTIME_POOL", "default"),
        "mode": "pipeline" if is_pipeline else "agent",
    })

    try:
        if is_pipeline:
            from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, serialize_pipeline_result
            from engine.agent_executor import build_tool_registry

            async def on_node_start(node_id: str, tool_name: str) -> None:
                await _publish(execution_id, {
                    "event": "node_start", "node_id": node_id, "tool_name": tool_name,
                })

            async def on_node_complete(node_id: str, status: str, duration_ms: int,
                                       output: Any, error_message: str | None = None,
                                       error_type: str | None = None) -> None:
                evt: dict[str, Any] = {
                    "event": "node_complete", "node_id": node_id,
                    "status": status, "duration_ms": duration_ms,
                }
                if status == "failed" and error_message:
                    evt["error"] = error_message[:2000]
                    if error_type:
                        evt["error_type"] = error_type
                elif output is not None:
                    out_text = str(output) if not isinstance(output, str) else output
                    evt["output_preview"] = out_text[:500]
                await _publish(execution_id, evt)

            pipeline_config = loaded["pipeline_config"] or {}
            raw_nodes = pipeline_config.get("nodes", [])
            nodes = parse_pipeline_nodes(raw_nodes)
            for node in nodes:
                if node.tool_name == "web_search" and "query" not in node.arguments:
                    node.arguments["query"] = message

            registry = build_tool_registry(loaded["tool_names"])
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
            result = await executor.execute(nodes, {"user_message": message, "__execution_id": execution_id, **context})
            serialized = serialize_pipeline_result(result)
            final_text = ""
            if result.final_output:
                # 50 KB cap matches the DB output_message column.
                final_text = (
                    result.final_output if isinstance(result.final_output, str)
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
                err_text = ("; ".join(node_errs) or f"failed nodes: {','.join(failed_nodes)}")[:2000]

            await _mark_done(execution_id, pipeline_status, final_text, err_text)
            await _publish(execution_id, {
                "event": "done" if pipeline_status == "completed" else "error",
                "execution_id": execution_id,
                "output": final_text, "summary": serialized,
                **({"error": err_text} if err_text else {}),
            })
        else:
            from engine.agent_executor import (
                AgentExecutor, build_tool_registry, resolve_asset_schemas,
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
            )
            llm_router = LLMRouter()
            _tool_cfg = loaded["model_cfg"].get("tool_config") or {}
            _asset_schemas = await resolve_asset_schemas(_tool_cfg)
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
                # Apply tool-schema injection here too so the NATS
                # consumer path behaves the same as the inline path.
                tool_config=_tool_cfg,
                asset_schemas=_asset_schemas,
            )
            result = await executor.invoke(message)
            # AgentExecutor returns ExecutionResult(output, tool_calls, input_tokens,
            # output_tokens, cost, ...). Pass these through so /executions and
            # /analytics show real numbers instead of nulls.
            output = getattr(result, "output", None) or str(result)
            await _mark_done(
                execution_id, "completed", str(output)[:4000], None,
                input_tokens=getattr(result, "input_tokens", None),
                output_tokens=getattr(result, "output_tokens", None),
                cost=getattr(result, "cost", None),
            )
            await _publish(execution_id, {
                "event": "done", "execution_id": execution_id,
                "output": str(output)[:4000],
                "input_tokens": getattr(result, "input_tokens", None),
                "output_tokens": getattr(result, "output_tokens", None),
                "cost": getattr(result, "cost", None),
            })
    except Exception as e:
        logger.exception("consumer: execution %s failed: %s", execution_id, e)
        await _mark_done(execution_id, "failed", None, str(e)[:2000])
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

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
                ctype = CONTENT_TYPE_LATEST.encode() if isinstance(CONTENT_TYPE_LATEST, str) else CONTENT_TYPE_LATEST
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

    logger.info("consumer: starting pool=%s backend=%s", pool, backend_name)

    health_port = int(os.environ.get("HEALTH_PORT", "8001"))
    health_task = asyncio.create_task(_serve_health(health_port))

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
            "consume via their own entrypoint). Exiting idle.", backend_name,
        )
        # Sleep forever so the pod stays alive under liveness probes.
        await stop.wait()
        return

    # NATS: drain the per-pool subject.
    try:
        async for msg in backend.stream(pool):
            if stop.is_set():
                break
            task_id = msg.get("task_id", "?")
            payload = msg.get("payload") or msg
            logger.info("consumer: picked task %s from agents.%s", task_id, pool)
            # Run each job inside a task so the loop can keep pulling while
            # long jobs run (bounded by concurrency env in the Helm chart).
            asyncio.create_task(_run_one(payload))
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
