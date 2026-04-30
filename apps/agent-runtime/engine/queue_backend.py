"""Queue-backend abstraction — Celery (default) or NATS JetStream."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


class QueueBackend:
    """Abstract base — two subclasses live below."""
    async def submit(self, queue_name: str, payload: dict) -> str: ...
    async def status(self, task_id: str) -> dict: ...
    async def stream(self, queue_name: str) -> AsyncIterator[dict]: ...


class CeleryBackend(QueueBackend):
    """Thin wrapper over the existing Celery app. Preserves current
    behaviour 1:1 so turning this on changes nothing."""

    def __init__(self) -> None:
        try:
            from worker.celery_app import celery_app, execute_agent_task  # type: ignore
            self.celery_app = celery_app
            self._execute = execute_agent_task
        except Exception as e:
            logger.warning("CeleryBackend failed to import worker tasks: %s", e)
            self.celery_app = None
            self._execute = None

    async def submit(self, queue_name: str, payload: dict) -> str:
        if self._execute is None:
            raise RuntimeError("Celery not available; install celery + redis")
        # Route to per-pool queue name. If the caller already used a
        # full queue name it passes through unchanged.
        queue = queue_name if "." in queue_name else f"celery.pool.{queue_name}"
        # apply_async to named queue; Celery routes via its broker.
        async_result = self._execute.apply_async(kwargs=payload, queue=queue)
        return async_result.id

    async def status(self, task_id: str) -> dict:
        if self.celery_app is None:
            return {"state": "UNKNOWN", "result": None}
        res = self.celery_app.AsyncResult(task_id)
        return {"state": res.state, "result": res.result if res.ready() else None}

    async def stream(self, queue_name: str) -> AsyncIterator[dict]:
        # Celery doesn't stream natively — this path is only for NATS.
        # We yield nothing so a caller that iterates on `stream` for
        # celery just gets an empty iterator (consumer runs in celery
        # worker instead).
        if False:
            yield {}


class NATSBackend(QueueBackend):
    """JetStream-backed queue. Imports are lazy so Celery deployments
    don't pay the dependency cost."""

    def __init__(self) -> None:
        try:
            import nats  # type: ignore
            self._nats = nats
        except ImportError as e:
            logger.warning("nats-py not installed; NATSBackend unavailable: %s", e)
            self._nats = None
        self._nc = None
        self._js = None
        self._lock = asyncio.Lock()

    async def _ensure(self):
        if self._nats is None:
            raise RuntimeError("nats-py is not installed (pip install nats-py)")
        if self._nc is not None and self._nc.is_connected:
            return
        async with self._lock:
            if self._nc is not None and self._nc.is_connected:
                return
            url = os.environ.get("NATS_URL", "nats://abenix-nats:4222")
            user = os.environ.get("NATS_USER", "abenix")
            password = os.environ.get("NATS_PASSWORD", "abenix-dev")
            self._nc = await self._nats.connect(url, user=user, password=password)
            self._js = self._nc.jetstream()
            # Ensure our stream exists. Idempotent.
            try:
                await self._js.add_stream(name="agents", subjects=["agents.>"])
            except Exception as e:
                logger.debug("nats add_stream agents (likely already exists): %s", e)

    async def submit(self, queue_name: str, payload: dict) -> str:
        await self._ensure()
        task_id = str(uuid.uuid4())
        subject = f"agents.{queue_name}"
        body = json.dumps({"task_id": task_id, "payload": payload}).encode()
        await self._js.publish(subject, body)
        return task_id

    async def status(self, task_id: str) -> dict:
        # JetStream isn't a K/V store — status lives in the DB execution row.
        # Callers should query the executions table directly; we return
        # UNKNOWN here so the interface stays consistent.
        return {"state": "UNKNOWN", "result": None,
                "note": "Use the executions endpoint for NATS-backed status"}

    async def stream(self, queue_name: str) -> AsyncIterator[dict]:
        await self._ensure()
        subject = f"agents.{queue_name}"
        psub = await self._js.pull_subscribe(
            subject,
            durable=f"abenix-{queue_name}-consumer",
        )
        try:
            while True:
                try:
                    msgs = await psub.fetch(1, timeout=5)
                except Exception:
                    # Nothing pending — just keep polling. Prevents a
                    # tight loop against JetStream and yields cleanly if
                    # the consumer is cancelled by an outer task.
                    await asyncio.sleep(0)
                    continue
                for msg in msgs:
                    try:
                        data = json.loads(msg.data.decode("utf-8"))
                        yield data
                        await msg.ack()
                    except Exception as e:
                        logger.exception("NATS stream decode failed: %s", e)
                        await msg.nak()
        finally:
            try: await psub.unsubscribe()
            except Exception: pass


_backend: Optional[QueueBackend] = None


def get_queue_backend() -> QueueBackend:
    """Return the active queue backend. Honours QUEUE_BACKEND env;
    falls back to Celery if NATS is requested but unavailable."""
    global _backend
    if _backend is not None:
        return _backend

    requested = os.environ.get("QUEUE_BACKEND", "celery").lower()
    if requested == "nats":
        candidate = NATSBackend()
        if candidate._nats is None:
            logger.warning("QUEUE_BACKEND=nats but nats-py missing — falling back to Celery")
            _backend = CeleryBackend()
        else:
            logger.info("Using NATS JetStream queue backend")
            _backend = candidate
    else:
        _backend = CeleryBackend()
    return _backend
