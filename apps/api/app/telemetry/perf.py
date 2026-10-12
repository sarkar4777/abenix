"""Low-overhead measurement for the ingest: sample rings the garbage collector never walks, and a
stall tracer that names the code holding the event loop."""

from __future__ import annotations

import gc
import logging
import sys
import threading
import time
import traceback
from array import array

logger = logging.getLogger("telemetry.perf")


class Ring:
    """The last n (time, value) samples in two flat arrays, so no per-sample objects stay alive."""

    def __init__(self, n: int = 8000) -> None:
        self.n = n
        self.t = array("d", [0.0]) * n
        self.v = array("d", [0.0]) * n
        self.i = 0
        self.count = 0

    def add(self, at: float, value: float) -> None:
        self.t[self.i] = at
        self.v[self.i] = value
        self.i = (self.i + 1) % self.n
        if self.count < self.n:
            self.count += 1

    def since(self, oldest: float) -> list[float]:
        if not self.count:
            return []
        t, v = self.t, self.v
        if self.count < self.n:
            return [v[k] for k in range(self.count) if t[k] >= oldest]
        return [v[k] for k in range(self.n) if t[k] >= oldest]

    def __bool__(self) -> bool:
        return self.count > 0


def tune_gc() -> None:
    """Move everything loaded so far out of the collector's way, and collect young objects less often.

    Called at start and again once the connections and their client libraries are up.
    """
    gc.collect()
    gc.freeze()
    gc.set_threshold(20000, 50, 50)


def sched_ms() -> tuple[float, float]:
    """This thread's CPU time and time spent runnable but not scheduled, from the kernel."""
    try:
        with open("/proc/thread-self/schedstat", encoding="ascii") as f:
            run, wait = f.read().split()[:2]
        return int(run) / 1e6, int(wait) / 1e6
    except (OSError, ValueError):
        return time.thread_time() * 1000, 0.0


class CpuWait:
    """Share of wall time the loop thread was runnable but the node gave it no CPU."""

    def __init__(self) -> None:
        self.at = time.monotonic()
        self.cpu, self.wait = sched_ms()
        self.pct = 0.0
        self.cpu_pct = 0.0

    def sample(self) -> None:
        now = time.monotonic()
        cpu, wait = sched_ms()
        span = (now - self.at) * 1000
        if span >= 1000:
            self.pct = round(100 * (wait - self.wait) / span, 1)
            self.cpu_pct = round(100 * (cpu - self.cpu) / span, 1)
            self.at, self.cpu, self.wait = now, cpu, wait


class GcTimer:
    """How long each collection held the interpreter, by generation.

    Wall time includes time the thread was descheduled, so CPU time is kept apart.
    """

    def __init__(self) -> None:
        self.t0 = 0.0
        self.max_ms = [0.0, 0.0, 0.0]
        self.cpu_max_ms = [0.0, 0.0, 0.0]
        self.c0 = 0.0
        self.count = [0, 0, 0]
        self.total_ms = 0.0
        self.slow_last = False
        self.diag_at = 0.0
        self.diag: dict = {}

    def __call__(self, phase: str, info: dict) -> None:
        if phase == "start":
            gen = int(info.get("generation", 0))
            if self.slow_last and time.monotonic() - self.diag_at > 60:
                # the last collection was slow, see what this one is about to walk
                self.diag_at = time.monotonic()
                self.slow_last = False
                try:
                    objs = gc.get_objects(gen)
                    from collections import Counter

                    top = Counter(type(o).__name__ for o in objs).most_common(6)
                    big = sorted(
                        (
                            (len(o), type(o).__name__)
                            for o in objs
                            if isinstance(o, (list, dict, set, tuple))
                        ),
                        reverse=True,
                    )[:3]
                    self.diag = {
                        "generation": gen,
                        "objects": len(objs),
                        "top": top,
                        "largest": big,
                    }
                    del objs
                    logger.warning(
                        "slow collections, generation %s holds %s", gen, self.diag
                    )
                except Exception:  # noqa: BLE001
                    pass
            self.c0 = time.thread_time()
            self.t0 = time.perf_counter()
            return
        gen = int(info.get("generation", 0))
        ms = (time.perf_counter() - self.t0) * 1000
        cpu = (time.thread_time() - self.c0) * 1000
        if cpu > self.cpu_max_ms[gen]:
            self.cpu_max_ms[gen] = cpu
        self.count[gen] += 1
        self.total_ms += ms
        if ms > self.max_ms[gen]:
            self.max_ms[gen] = ms
        if cpu > 50:
            self.slow_last = True

    def install(self) -> None:
        if self not in gc.callbacks:
            gc.callbacks.append(self)

    def snapshot(self) -> dict:
        return {
            "gc_max_ms": [round(x, 1) for x in self.max_ms],
            "gc_cpu_max_ms": [round(x, 1) for x in self.cpu_max_ms],
            "gc_count": list(self.count),
            "gc_total_ms": round(self.total_ms, 1),
            "gc_diag": self.diag,
        }


class StallTracer:
    """A watchdog thread: when the loop has not ticked for threshold_ms, log where it is stuck."""

    def __init__(self, threshold_ms: float = 100.0, every_s: float = 10.0) -> None:
        self.threshold = threshold_ms / 1000.0
        self.every = every_s
        self.beat = time.monotonic()
        self.loop_thread = threading.get_ident()
        self.stalls = 0
        self.last: str | None = None
        self._logged = 0.0
        self._stop = threading.Event()

    def tick(self) -> None:
        self.beat = time.monotonic()

    def start(self) -> None:
        self.loop_thread = threading.get_ident()
        threading.Thread(target=self._watch, name="stall-tracer", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _watch(self) -> None:
        caught = False
        while not self._stop.wait(0.02):
            late = time.monotonic() - self.beat
            if late < self.threshold:
                caught = False
                continue
            if caught:
                continue
            caught = True
            self.stalls += 1
            frame = sys._current_frames().get(self.loop_thread)
            if frame is None:
                continue
            stack = "".join(traceback.format_stack(frame, limit=14))
            self.last = stack[-3000:]
            now = time.monotonic()
            if now - self._logged >= self.every:
                self._logged = now
                logger.warning(
                    "event loop stalled %.0f ms, it was here:\n%s", late * 1000, stack
                )
