"""Multi-tenant fairness load test.

Phase 1: Baseline — tenant B alone (5 concurrent)
Phase 2: Noisy neighbor — A fires 500 concurrent while B fires 5
Compare B's p95 across phases.
"""
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(r"C:\Users\sarka\projects\agentforge")
TOKEN_A = (ROOT / ".tmp_tokenA.txt").read_text().strip()
TOKEN_B = (ROOT / ".tmp_tokenB.txt").read_text().strip()
TENANT_A = (ROOT / ".tmp_tenantA.txt").read_text().strip()
TENANT_B = (ROOT / ".tmp_tenantB.txt").read_text().strip()
BASE = "http://localhost:8000"
AGENT_ID = "d4ad3150-8085-45dd-8caa-a1a2492c1061"  # ContractIQ Recommendation Engine (shared)


async def one_call(client, token, label, idx):
    headers = {"Authorization": f"Bearer {token}"}
    body = {"message": f"hi {label}-{idx}", "stream": False, "wait": False}
    t0 = time.perf_counter()
    err = None
    code = 0
    try:
        r = await client.post(
            f"{BASE}/api/agents/{AGENT_ID}/execute",
            json=body,
            headers=headers,
            timeout=60.0,
        )
        code = r.status_code
        body_snip = r.text[:200] if code >= 400 else ""
    except Exception as e:
        err = str(e)[:120]
        body_snip = ""
    dt = time.perf_counter() - t0
    return {"label": label, "idx": idx, "status": code, "latency_s": dt, "err": err, "body": body_snip}


def stats(rs):
    lats = [r["latency_s"] for r in rs if r["status"] and r["status"] < 500]
    if not lats:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "max": None, "errors": len(rs)}
    lats_sorted = sorted(lats)
    return {
        "n": len(lats),
        "p50": round(lats_sorted[len(lats_sorted) // 2] * 1000, 1),
        "p95": round(lats_sorted[int(0.95 * len(lats_sorted))] * 1000, 1) if len(lats_sorted) >= 20 else round(max(lats_sorted) * 1000, 1),
        "p99": round(lats_sorted[int(0.99 * len(lats_sorted))] * 1000, 1) if len(lats_sorted) >= 100 else round(max(lats_sorted) * 1000, 1),
        "max": round(max(lats_sorted) * 1000, 1),
        "avg": round(sum(lats_sorted) / len(lats_sorted) * 1000, 1),
        "errors": sum(1 for r in rs if r["status"] >= 500 or r["err"]),
        "rate_limited_429": sum(1 for r in rs if r["status"] == 429),
        "status_breakdown": dict((c, sum(1 for r in rs if r["status"] == c)) for c in sorted({r["status"] for r in rs})),
    }


async def phase_baseline_B():
    print("PHASE 1: Tenant B baseline (5 concurrent, 3 rounds)")
    async with httpx.AsyncClient(http2=False, limits=httpx.Limits(max_connections=200)) as client:
        all_rs = []
        for rnd in range(3):
            rs = await asyncio.gather(*[one_call(client, TOKEN_B, "B-base", i + rnd * 5) for i in range(5)])
            all_rs.extend(rs)
        return stats(all_rs), all_rs


async def phase_noisy_neighbor():
    print("PHASE 2: A=500 concurrent, B=5 concurrent (simultaneous)")
    async with httpx.AsyncClient(http2=False, limits=httpx.Limits(max_connections=600)) as client:
        # Warm up
        await asyncio.sleep(0.2)
        # Fire A and B concurrently; B starts a tiny bit later so A is already in flight
        tasks_A = [one_call(client, TOKEN_A, "A-noisy", i) for i in range(500)]
        tasks_B_first = [one_call(client, TOKEN_B, "B-victim", i) for i in range(5)]

        async def fire_B_later():
            await asyncio.sleep(0.5)  # let A start saturating
            return await asyncio.gather(*tasks_B_first)

        results_all = await asyncio.gather(asyncio.gather(*tasks_A), fire_B_later())
        rs_A = results_all[0]
        rs_B = results_all[1]
        return stats(rs_A), stats(rs_B), rs_A, rs_B


async def main():
    print(f"Tenant A={TENANT_A}  Tenant B={TENANT_B}")
    base_B_stats, base_B_rs = await phase_baseline_B()
    print("Baseline B:", json.dumps(base_B_stats, indent=2))
    A_stats, B_stats, rsA, rsB = await phase_noisy_neighbor()
    print("Noisy A:", json.dumps(A_stats, indent=2))
    print("Noisy B (under A pressure):", json.dumps(B_stats, indent=2))

    # Verdict
    base_p95 = base_B_stats.get("p95") or 0
    under_p95 = B_stats.get("p95") or 0
    print("\nVERDICT")
    print(f"  B baseline p95: {base_p95} ms")
    print(f"  B noisy    p95: {under_p95} ms")
    ratio = (under_p95 / base_p95) if base_p95 else 0
    print(f"  ratio: {ratio:.2f}x")
    starved = B_stats.get("n", 0) < 4 or any(r["status"] in (429, 503) for r in rsB)
    print(f"  starved (B unable to complete or 429/503): {starved}")
    # sample 3 raw B responses
    print("\nSample noisy-B responses:")
    for r in rsB[:5]:
        print(f"  status={r['status']} latency_ms={int(r['latency_s']*1000)} err={r['err']} body={r['body'][:80]}")
    print("\nSample noisy-A responses (first 3):")
    for r in rsA[:3]:
        print(f"  status={r['status']} latency_ms={int(r['latency_s']*1000)} err={r['err']} body={r['body'][:60]}")


if __name__ == "__main__":
    asyncio.run(main())
