from __future__ import annotations

from types import SimpleNamespace

from prometheus_client import REGISTRY

from engine.metrics import observe_execution
from engine.queue_backend import NATSBackend


def _count(pool: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "abenix_execution_duration_seconds_count",
            {"pool": pool, "status": status},
        )
        or 0.0
    )


def test_finished_run_lands_in_the_pool_histogram():
    before = _count("chat", "completed")
    observe_execution("chat", "completed", 4200)
    observe_execution("chat", "completed", None)
    assert _count("chat", "completed") == before + 1


async def test_pending_reads_the_durable_consumer():
    class _JS:
        async def consumer_info(self, stream, durable):
            assert (stream, durable) == ("agents", "abenix-chat-consumer")
            return SimpleNamespace(num_pending=7, num_ack_pending=2)

    b = NATSBackend.__new__(NATSBackend)
    b._js = _JS()

    async def _noop():
        return None

    b._ensure = _noop
    assert await b.pending("chat") == 7
