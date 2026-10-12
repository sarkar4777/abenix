"""The ingest's own measurements: GC-free sample rings and the stall tracer."""

from __future__ import annotations

import gc
import time

from app.telemetry import perf


def test_ring_keeps_the_newest_and_filters_by_time():
    r = perf.Ring(4)
    for i in range(6):
        r.add(float(i), float(i * 10))
    assert sorted(r.since(0)) == [20.0, 30.0, 40.0, 50.0]
    assert sorted(r.since(4)) == [40.0, 50.0]
    assert all(isinstance(x, type) for x in gc.get_referents(r.t))


def test_stall_tracer_names_the_blocking_code():
    tr = perf.StallTracer(threshold_ms=50, every_s=0)
    tr.start()

    def hold_the_loop():
        time.sleep(0.3)

    tr.tick()
    hold_the_loop()
    time.sleep(0.05)
    tr.stop()
    assert tr.stalls >= 1 and "hold_the_loop" in (tr.last or "")


def test_gc_timer_keeps_cpu_time_apart_from_wall_time():
    import gc

    t = perf.GcTimer()
    t("start", {"generation": 0})
    time.sleep(0.03)
    t("stop", {"generation": 0})
    snap = t.snapshot()
    assert snap["gc_max_ms"][0] >= 25
    assert snap["gc_cpu_max_ms"][0] < 10
    assert gc.isenabled()


def test_cpu_wait_reports_shares_after_a_second():
    w = perf.CpuWait()
    w.at -= 2
    w.sample()
    assert 0 <= w.pct <= 100 and w.cpu_pct >= 0


def test_load_test_tally_counts_buckets_before_they_expire():
    import asyncio

    from app.telemetry import keys as K
    from app.telemetry import loadtest as L
    from telemetry_fakes import FakeRedis

    async def go():
        r = FakeRedis()
        start = 1000.5
        tally = L.RateTally(r, ["t"], start)
        for sec in range(1001, 1061):
            await r.hincrby(K.rate("t", sec), "_total", 100)
            await r.hincrby(K.rate("t", sec), "g/n", 100)
            await tally.read_until(sec)
            if sec - 10 > 1000:
                await r.delete(K.rate("t", sec - 10))
        assert tally.total("t") == 6000 and tally.total("t", "g/n") == 6000

    asyncio.run(go())
