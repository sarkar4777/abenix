import json
import os
import subprocess
import time
import urllib.request

API = "http://localhost:8000"
PG_NS = "abenix"
PG_POD = "abenix-postgresql-0"
DB_NAME = "abenix"
DB_USER = "postgres"
PG_PASSWORD = os.environ["PG_PASSWORD"]


def pg_query(sql: str) -> str:
    cmd = [
        "kubectl",
        "exec",
        "-n",
        PG_NS,
        PG_POD,
        "--",
        "bash",
        "-c",
        f"PGPASSWORD='{PG_PASSWORD}' psql -U {DB_USER} -d {DB_NAME} -At -c \"{sql}\"",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: rc={r.returncode} stderr={r.stderr[:300]}")
    return r.stdout.strip()


def login():
    body = json.dumps({"email": "admin@abenix.dev", "password": "Admin123456"}).encode()
    req = urllib.request.Request(
        f"{API}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return data["data"]["access_token"]


def xact_total() -> tuple[int, int]:
    """Return (xact_commit, xact_rollback) for the abenix DB."""
    out = pg_query(
        f"SELECT xact_commit, xact_rollback FROM pg_stat_database WHERE datname='{DB_NAME}'"
    )
    parts = out.split("|")
    return int(parts[0]), int(parts[1])


def hit(token: str, path: str) -> tuple[int, float]:
    req = urllib.request.Request(
        f"{API}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        e.read()
        code = e.code
    return code, time.time() - t0


def baseline_rate(seconds: int = 10) -> float:
    """Measure xact/sec with NO load, to subtract background noise."""
    c0, r0 = xact_total()
    t0 = time.time()
    time.sleep(seconds)
    c1, r1 = xact_total()
    elapsed = time.time() - t0
    return ((c1 - c0) + (r1 - r0)) / elapsed


def bench(path: str, n: int, token: str, baseline_xps: float):
    hit(token, path)
    time.sleep(2)

    c0, r0 = xact_total()
    times = []
    codes = []
    t_start = time.time()
    for _ in range(n):
        code, t = hit(token, path)
        codes.append(code)
        times.append(t)
    elapsed = time.time() - t_start
    time.sleep(2)
    c1, r1 = xact_total()

    raw_delta = (c1 - c0) + (r1 - r0)
    # subtract background: baseline_xps * elapsed
    bg = baseline_xps * elapsed
    net = raw_delta - bg
    avg_ms = sum(times) / len(times) * 1000
    print(
        f"path={path} n={n} codes={set(codes)} elapsed={elapsed:.2f}s avg={avg_ms:.0f}ms "
        f"raw_delta={raw_delta} bg_est={bg:.1f} net={net:.1f} per_req={net/n:.2f}"
    )


def main():
    token = login()
    print(f"token_len={len(token)}")
    bg = baseline_rate(15)
    print(f"baseline_xps={bg:.2f}")
    for path in [
        "/api/agents?limit=20",
        "/api/executions?limit=20",
        "/api/agents?limit=20",
        "/api/executions?limit=20",
    ]:
        bench(path, 30, token, bg)


if __name__ == "__main__":
    main()
