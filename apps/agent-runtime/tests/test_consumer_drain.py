"""A stopping runtime pod takes no new work, hands back what arrives late, and finishes the runs it holds."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[1]
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

import consumer  # noqa: E402


class Msg:
    def __init__(self, n: int) -> None:
        self.data = {"task_id": f"t{n}"}
        self.calls: list = []

    async def nak(self, delay=None):
        self.calls.append("nak")


class Stream:
    """Yields messages when told, like a queue that is idle most of the time."""

    def __init__(self) -> None:
        self.q: asyncio.Queue = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.q.get()


def test_stop_ends_an_idle_loop_and_drain_lets_runs_finish():
    async def go():
        stream, stop = Stream(), asyncio.Event()
        gate, in_flight, finished = asyncio.Semaphore(4), set(), []

        async def handle(qm):
            await asyncio.sleep(0.3)
            finished.append(qm.data["task_id"])

        loop = asyncio.create_task(
            consumer.run_loop(stream, stop, gate, in_flight, handle)
        )
        await stream.q.put(Msg(1))
        await asyncio.sleep(0.05)
        assert len(in_flight) == 1
        stop.set()
        # the queue is idle, the loop still ends at once
        await asyncio.wait_for(loop, 1)
        await consumer.drain(in_flight, 5)
        assert finished == ["t1"]

    asyncio.run(go())


def test_a_message_after_stop_goes_back_to_the_queue():
    async def go():
        stop = asyncio.Event()
        taken = []

        async def handle(qm):
            taken.append(qm)

        late = Msg(2)
        stop_and_send = asyncio.Event()

        class Racing(Stream):
            async def __anext__(self):
                await stop_and_send.wait()
                stop.set()
                return late

        loop = asyncio.create_task(
            consumer.run_loop(Racing(), stop, asyncio.Semaphore(1), set(), handle)
        )
        await asyncio.sleep(0.01)
        stop_and_send.set()
        await asyncio.wait_for(loop, 1)
        assert not taken
        assert late.calls == ["nak"]

    asyncio.run(go())


def test_runs_past_the_drain_deadline_are_cancelled_for_another_pod():
    async def go():
        cancelled = []

        async def slow():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        t = asyncio.create_task(slow())
        await asyncio.sleep(0)
        await consumer.drain({t}, 0.05)
        await asyncio.sleep(0)
        assert cancelled == [True]

    asyncio.run(go())
