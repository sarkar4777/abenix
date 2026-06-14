import json
import subprocess
import time
import urllib.request

API = "http://localhost:8000"
PG_POD = "abenix-postgresql-0"
DB_NAME = "abenix"
DB_USER = "postgres"


def pg_query(sql: str) -> str:
    cmd = [
        "kubectl",
        "exec",
        PG_POD,
        "--",
        "psql",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-At",
        "-c",
        sql,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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


def bench(path: str, n: int, token: str):
    # Warm up + flush any background activity
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

    delta = (c1 - c0) + (r1 - r0)
    avg_ms = sum(times) / len(times) * 1000
    print(f"path={path} n={n} codes={set(codes)} elapsed={elapsed:.2f}s avg={avg_ms:.0f}ms xact_delta={delta} per_req={delta/n:.2f}")


def main():
    token = login()
    print(f"token_len={len(token)}")
    # Match the original methodology: 30 sequential GETs
    for path in ["/api/agents?limit=20", "/api/executions?limit=20"]:
        bench(path, 30, token)


if __name__ == "__main__":
    main()
