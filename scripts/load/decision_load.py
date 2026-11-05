"""Concurrent decision evaluation load, with a publish in the middle of the run.

    python decision_load.py --base http://abenix-api:8000 --token JWT --key some.decision \
        --concurrency 500 --seconds 60 --publish-at 20 --publish-version 2

Exits 0 when every threshold holds, 1 when one fails, 2 when it could not run or got no answers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time

try:
    import httpx
except ImportError as exc:
    print(f"decision load could not run, missing {exc.name}", file=sys.stderr)
    sys.exit(2)

FACTS = [
    {"shipment": {"date": "2026-03-01", "postcode": "IV27", "weightKg": 120}},
    {"shipment": {"date": "2026-03-01", "postcode": "ZE2", "weightKg": 30}},
    {"shipment": {"date": "2026-06-01", "postcode": "SW1A", "weightKg": 500}},
]


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[k]


def check(name: str, measured: float, limit: float, ceiling: bool = True) -> bool:
    ok = measured <= limit if ceiling else measured >= limit
    print(
        f"{'PASS' if ok else 'FAIL'} {name} measured={measured} limit={limit}",
        flush=True,
    )
    return ok


def evaluate(
    report: dict, min_rps: float, max_error_rate: float, max_p95_ms: float
) -> int:
    failed = sum(report["errors"].values())
    if not report["ok"]:
        print(f"no successful requests, errors {report['errors']}", flush=True)
        return 2
    results = []
    if min_rps > 0:
        results.append(check("rps", report["rps"], min_rps, ceiling=False))
    if max_error_rate >= 0:
        rate = round(failed / (report["ok"] + failed), 4)
        results.append(check("error_rate", rate, max_error_rate))
    if max_p95_ms > 0:
        results.append(check("p95_ms", report["p95_ms"], max_p95_ms))
    return 0 if all(results) else 1


async def run(a: argparse.Namespace, share: int, do_publish: bool) -> dict:
    limits = httpx.Limits(max_connections=share, max_keepalive_connections=share)
    headers = {"Authorization": f"Bearer {a.token}", "Content-Type": "application/json"}
    lat: list[float] = []
    errors: dict[str, int] = {}
    versions: dict[int, int] = {}
    hashes: dict[str, set[str]] = {}
    stop = time.monotonic() + a.seconds

    async with httpx.AsyncClient(
        base_url=a.base, headers=headers, limits=limits, timeout=30
    ) as c:

        async def worker(i: int) -> None:
            rnd = random.Random(i)
            while time.monotonic() < stop:
                f = rnd.choice(FACTS)
                t0 = time.perf_counter()
                try:
                    r = await c.post(
                        f"/api/decisions/{a.key}/evaluate",
                        json={
                            "facts": f,
                            "as_of": f["shipment"]["date"],
                            "trace": False,
                        },
                    )
                    dt = (time.perf_counter() - t0) * 1000
                    if r.status_code == 200:
                        d = r.json()["data"]
                        lat.append(dt)
                        versions[d["version"]["version"]] = (
                            versions.get(d["version"]["version"], 0) + 1
                        )
                        hashes.setdefault(
                            f"{json.dumps(f, sort_keys=True)}|{d['version']['version']}",
                            set(),
                        ).add(d["trace_hash"])
                    else:
                        errors[str(r.status_code)] = (
                            errors.get(str(r.status_code), 0) + 1
                        )
                except Exception as e:  # noqa: BLE001
                    errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1

        async def publisher() -> None:
            if not do_publish or not a.publish_at or not a.publish_version:
                return
            await asyncio.sleep(a.publish_at)
            r = await c.post(
                f"/api/decisions/{a.key}/versions/{a.publish_version}/publish", json={}
            )
            print(
                f"publish v{a.publish_version} at {a.publish_at}s -> {r.status_code}",
                flush=True,
            )

        t_start = time.monotonic()
        await asyncio.gather(publisher(), *(worker(i) for i in range(share)))
        took = time.monotonic() - t_start
    return {
        "lat": lat,
        "errors": errors,
        "versions": versions,
        "hashes": {k: sorted(v) for k, v in hashes.items()},
        "took": took,
    }


def _proc(args: tuple) -> dict:
    a, share, first = args
    return asyncio.run(run(a, share, first))


def main() -> int:
    import multiprocessing as mp

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--concurrency", type=int, default=500)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--publish-at", type=int, default=0)
    ap.add_argument("--publish-version", type=int, default=0)
    # one httpx client degrades past a few dozen connections, so spread them over processes
    ap.add_argument(
        "--procs", type=int, default=0, help="0 means one per 32 connections"
    )
    ap.add_argument("--min-rps", type=float, default=100, help="0 means not checked")
    ap.add_argument(
        "--max-error-rate", type=float, default=0.05, help="below 0 means not checked"
    )
    ap.add_argument(
        "--max-p95-ms", type=float, default=5000, help="0 means not checked"
    )
    a = ap.parse_args()
    if a.concurrency <= 0 or a.seconds <= 0:
        ap.error("--concurrency and --seconds must be above 0")
    a.procs = a.procs or max(1, -(-a.concurrency // 32))
    share = max(1, a.concurrency // a.procs)
    try:
        with mp.Pool(a.procs) as pool:
            parts = pool.map(_proc, [(a, share, i == 0) for i in range(a.procs)])
    except Exception as exc:  # noqa: BLE001
        print(f"decision load could not run, {exc!r}", file=sys.stderr, flush=True)
        return 2
    lat = [x for p in parts for x in p["lat"]]
    errors: dict[str, int] = {}
    versions: dict[int, int] = {}
    hashes: dict[str, set[str]] = {}
    for p in parts:
        for k, v in p["errors"].items():
            errors[k] = errors.get(k, 0) + v
        for k, v in p["versions"].items():
            versions[k] = versions.get(k, 0) + v
        for k, v in p["hashes"].items():
            hashes.setdefault(k, set()).update(v)
    took = max(p["took"] for p in parts)
    report = {
        "concurrency": share * a.procs,
        "procs": a.procs,
        "seconds": round(took, 1),
        "ok": len(lat),
        "errors": errors,
        "rps": round(len(lat) / took, 1),
        "p50_ms": round(pct(lat, 50), 1),
        "p95_ms": round(pct(lat, 95), 1),
        "p99_ms": round(pct(lat, 99), 1),
        "mean_ms": round(statistics.mean(lat), 1) if lat else 0,
        "versions_seen": versions,
        "nondeterministic_cases": sum(1 for v in hashes.values() if len(v) > 1),
    }
    print(json.dumps(report), flush=True)
    return evaluate(report, a.min_rps, a.max_error_rate, a.max_p95_ms)


if __name__ == "__main__":
    sys.exit(main())
