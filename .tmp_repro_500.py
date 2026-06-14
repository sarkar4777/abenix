"""Reproduce the 22/500 5xx rate from tenant A noisy-neighbor burst.
Captures response bodies for 5xx so we can identify root cause."""
import asyncio, json, time, collections
import httpx

BASE = "http://localhost:8000"
AGENT_ID = "d4ad3150-8085-45dd-8caa-a1a2492c1061"

TOKEN_A = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwYmUyNGNiNy1lOGQwLTQ0NTAtYmEzYS1iYmIyYTczZDNmN2IiLCJ0ZW5hbnRfaWQiOiI0NjFjZTY4OC1kZjczLTQ3OWUtOWU4MC00ZjEyYWQwMzcyYmYiLCJyb2xlIjoiQURNSU4iLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgxNDIyNzg5LCJpYXQiOjE3ODE0MjE4ODl9.RWnd_OTv7HwRoqz-kk_60-T9cPoNIN0ByKsaIJXMwrwnBcRliuJatTEMpBweERJ2LiSzbzm-xKrogd8WQkdUdxUdZIAQuFsV-PUNKWhsKIhKnK0isTmWVTbzH8jni9Y6009OmNxaqt5RbLH4_quYJhDxVDm6UoGx5nv1bkL1GS0LH06DdDtzTJdnI8Kj2L39Wt3Bk4vY4TFVT-5CPXl4XEAeB8zHnbII8DJb-Fz85H6fPhkAtMpTqjz2nkI8n5wt0SzkIq3DQswrzfsvvZHurFmFxh6ZpjcIozzrFDyCxCGYSCC1GDDXJozbP6K46mlrivvA7NfJuJeID4EXcefr6g"

async def one_call(client, idx):
    headers = {"Authorization": f"Bearer {TOKEN_A}"}
    body = {"message": f"hi noisy-{idx}", "stream": False, "wait": False}
    t0 = time.perf_counter()
    err, code, btxt = None, 0, ""
    try:
        r = await client.post(f"{BASE}/api/agents/{AGENT_ID}/execute", json=body, headers=headers, timeout=120.0)
        code = r.status_code
        btxt = r.text[:400] if code >= 400 else ""
    except Exception as e:
        err = type(e).__name__ + ":" + str(e)[:120]
    return {"idx": idx, "status": code, "latency_ms": int((time.perf_counter() - t0) * 1000), "err": err, "body": btxt}

async def main():
    async with httpx.AsyncClient(http2=False, limits=httpx.Limits(max_connections=600)) as client:
        rs = await asyncio.gather(*[one_call(client, i) for i in range(500)])
    breakdown = collections.Counter(r["status"] for r in rs)
    print("status_breakdown:", dict(breakdown))
    err_count = sum(1 for r in rs if r["err"])
    print(f"client_errors: {err_count}")
    fives = [r for r in rs if r["status"] >= 500]
    print(f"\n5xx COUNT: {len(fives)} of {len(rs)} ({len(fives)/len(rs)*100:.1f}%)")
    print("\nfirst 8 5xx response bodies:")
    for r in fives[:8]:
        print(f"  idx={r['idx']:3d} status={r['status']} lat={r['latency_ms']}ms body={r['body']!r}")
    # group bodies
    body_counts = collections.Counter(r["body"][:200] for r in fives)
    print("\n5xx body grouping:")
    for body, n in body_counts.most_common(5):
        print(f"  [{n}x] {body!r}")

if __name__ == "__main__":
    asyncio.run(main())
