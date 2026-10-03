"""Concurrent decision evaluation load, with a publish in the middle of the run.

    python decision_load.py --base http://abenix-api:8000 --token JWT --key some.decision \
        --concurrency 500 --seconds 60 --publish-at 20 --publish-version 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time

import httpx

FACTS = [
    {
        "import": {"date": "2026-03-01", "cnCode": "72011000", "netMassTonnes": 12},
        "importer": {"annualCbamMassTonnes": 120},
    },
    {
        "import": {"date": "2026-03-01", "cnCode": "31021000", "netMassTonnes": 3},
        "importer": {"annualCbamMassTonnes": 30},
    },
    {
        "import": {"date": "2026-06-01", "cnCode": "99999999", "netMassTonnes": 1},
        "importer": {"annualCbamMassTonnes": 500},
    },
]


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[k]


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
                        json={"facts": f, "as_of": f["import"]["date"], "trace": False},
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


def main() -> None:
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
    a = ap.parse_args()
    a.procs = a.procs or max(1, -(-a.concurrency // 32))
    share = max(1, a.concurrency // a.procs)
    with mp.Pool(a.procs) as pool:
        parts = pool.map(_proc, [(a, share, i == 0) for i in range(a.procs)])
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
    print(
        json.dumps(
            {
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
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
