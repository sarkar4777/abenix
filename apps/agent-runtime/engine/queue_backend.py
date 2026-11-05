"""Queue-backend abstraction. NATS JetStream runs queued agents, Celery is refused."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

# the JetStream default, so a durable created before this line behaves the same
ACK_WAIT_SECONDS = 30
# another process may delete a dedicated pool's durable, so a hit is only trusted this long
CONSUMER_CHECK_SECONDS = 60


def consumer_name(queue_name: str) -> str:
    return f"abenix-{queue_name}-consumer"


class QueueBackend:
    """Abstract base — two subclasses live below."""

    async def submit(self, queue_name: str, payload: dict) -> str: ...
    async def status(self, task_id: str) -> dict: ...
    async def stream(self, queue_name: str) -> AsyncIterator[dict]: ...

    async def pending(self, queue_name: str) -> int | None:
        return None

    async def ensure_consumer(self, queue_name: str) -> None:
        return None

    async def backlog(self, queue_name: str) -> int | None:
        return None

    async def remove_queue(self, queue_name: str) -> None:
        return None


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
        self._consumers_seen: dict[str, float] = {}

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

    async def ensure_consumer(self, queue_name: str) -> None:
        """Create the durable if it is missing, KEDA reads its lag before any pod exists."""
        await self._ensure()
        seen = self._consumers_seen.get(queue_name)
        if seen is not None and time.monotonic() - seen < CONSUMER_CHECK_SECONDS:
            return
        from nats.js.api import ConsumerConfig  # type: ignore
        from nats.js.errors import NotFoundError  # type: ignore

        durable = consumer_name(queue_name)
        try:
            await self._js.consumer_info("agents", durable)
        except NotFoundError:
            await self._js.add_consumer(
                "agents",
                config=ConsumerConfig(
                    name=durable,
                    durable_name=durable,
                    filter_subject=f"agents.{queue_name}",
                    ack_wait=ACK_WAIT_SECONDS,
                ),
            )
            logger.info("created durable %s", durable)
        self._consumers_seen[queue_name] = time.monotonic()

    async def submit(self, queue_name: str, payload: dict) -> str:
        await self.ensure_consumer(queue_name)
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

    async def pending(self, queue_name: str) -> int | None:
        await self._ensure()
        info = await self._js.consumer_info("agents", consumer_name(queue_name))
        return int(info.num_pending or 0)

    async def backlog(self, queue_name: str) -> int | None:
        """Runs still queued or held on this pool, None when it has no durable."""
        from nats.js.errors import NotFoundError  # type: ignore

        await self._ensure()
        try:
            info = await self._js.consumer_info("agents", consumer_name(queue_name))
        except NotFoundError:
            return None
        return int(info.num_pending or 0) + int(info.num_ack_pending or 0)

    async def remove_queue(self, queue_name: str) -> None:
        """Drop a retired pool's durable and its messages, a later durable would replay them."""
        from nats.js.errors import NotFoundError  # type: ignore

        await self._ensure()
        self._consumers_seen.pop(queue_name, None)
        try:
            await self._js.delete_consumer("agents", consumer_name(queue_name))
        except NotFoundError:
            pass
        await self._js.purge_stream("agents", subject=f"agents.{queue_name}")

    async def stream(self, queue_name: str) -> AsyncIterator[QueueMessage]:
        await self._ensure()
        subject = f"agents.{queue_name}"
        from nats.errors import TimeoutError as NatsTimeout  # type: ignore

        try:
            from nats.js.api import ConsumerConfig  # type: ignore

            config = ConsumerConfig(ack_wait=ACK_WAIT_SECONDS)
        except Exception:
            config = None
        psub = await self._js.pull_subscribe(
            subject,
            durable=consumer_name(queue_name),
            config=config,
        )
        try:
            while True:
                try:
                    msgs = await psub.fetch(1, timeout=5)
                except (NatsTimeout, asyncio.TimeoutError):
                    await asyncio.sleep(0)
                    continue
                except Exception as e:
                    # a lost NATS connection fails at once, do not spin on it
                    logger.warning("consumer: fetch from %s failed: %s", subject, e)
                    await asyncio.sleep(1)
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
