"""Queue-backend abstraction. NATS JetStream runs queued agents, Celery is refused."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

# the JetStream default, so a durable created before this line behaves the same
ACK_WAIT_SECONDS = 30


class QueueBackend:
    """Abstract base — two subclasses live below."""

    async def submit(self, queue_name: str, payload: dict) -> str: ...
    async def status(self, task_id: str) -> dict: ...
    async def stream(self, queue_name: str) -> AsyncIterator[dict]: ...


CELERY_UNSUPPORTED = (
    "QUEUE_BACKEND=celery cannot run agents on the runtime pools. Queued agent "
    "execution runs on NATS JetStream only: set scaling.queueBackend=nats, or "
    "set scaling.execRemote=false to run agents inline in the API."
)


class CeleryBackend(QueueBackend):
    """Placeholder for QUEUE_BACKEND=celery. Agent runs are not queued on Celery."""

    async def submit(self, queue_name: str, payload: dict) -> str:
        raise RuntimeError(CELERY_UNSUPPORTED)

    async def status(self, task_id: str) -> dict:
        return {"state": "UNKNOWN", "result": None, "note": CELERY_UNSUPPORTED}

    async def stream(self, queue_name: str) -> AsyncIterator["QueueMessage"]:
        raise RuntimeError(CELERY_UNSUPPORTED)
        yield  # pragma: no cover


class QueueMessage:
    """One delivery. The consumer acks it when the run is finished, not when it starts."""

    def __init__(self, data: dict, msg: Any = None) -> None:
        self.data = data
        self._msg = msg

    @property
    def num_delivered(self) -> int:
        try:
            return int(self._msg.metadata.num_delivered)
        except Exception:
            return 1

    async def ack(self) -> None:
        if self._msg is not None:
            await self._msg.ack()

    async def nak(self, delay: float | None = None) -> None:
        if self._msg is not None:
            await self._msg.nak(delay=delay)

    async def in_progress(self) -> None:
        if self._msg is not None:
            await self._msg.in_progress()


class NATSBackend(QueueBackend):
    """JetStream-backed queue, delivered at least once."""

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
            password = os.environ.get("NATS_PASSWORD") or None
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
        envelope: dict[str, Any] = {"task_id": task_id, "payload": payload}
        from engine.tracing import inject_carrier

        carrier = inject_carrier()
        if carrier:
            envelope["trace"] = carrier
        body = json.dumps(envelope).encode()
        await self._js.publish(subject, body)
        return task_id

    async def status(self, task_id: str) -> dict:
        # JetStream isn't a K/V store — status lives in the DB execution row.
        # Callers should query the executions table directly; we return
        # UNKNOWN here so the interface stays consistent.
        return {
            "state": "UNKNOWN",
            "result": None,
            "note": "Use the executions endpoint for NATS-backed status",
        }

    async def stream(self, queue_name: str) -> AsyncIterator[QueueMessage]:
        await self._ensure()
        subject = f"agents.{queue_name}"
        try:
            from nats.js.api import ConsumerConfig  # type: ignore

            config = ConsumerConfig(ack_wait=ACK_WAIT_SECONDS)
        except Exception:
            config = None
        psub = await self._js.pull_subscribe(
            subject,
            durable=f"abenix-{queue_name}-consumer",
            config=config,
        )
        try:
            while True:
                try:
                    msgs = await psub.fetch(1, timeout=5)
                except Exception:
                    await asyncio.sleep(0)
                    continue
                for msg in msgs:
                    try:
                        data = json.loads(msg.data.decode("utf-8"))
                    except Exception as e:
                        # undecodable forever, redelivering it would loop
                        logger.exception("NATS message decode failed: %s", e)
                        await msg.term()
                        continue
                    yield QueueMessage(data, msg)
        finally:
            try:
                await psub.unsubscribe()
            except Exception:
                pass


_backend: Optional[QueueBackend] = None


def get_queue_backend() -> QueueBackend:
    """Return the backend named by QUEUE_BACKEND. Only nats runs queued agents."""
    global _backend
    if _backend is not None:
        return _backend

    requested = os.environ.get("QUEUE_BACKEND", "celery").lower()
    if requested == "nats":
        _backend = NATSBackend()
    else:
        logger.warning(CELERY_UNSUPPORTED)
        _backend = CeleryBackend()
    return _backend
