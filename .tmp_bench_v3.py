import os, json, time, subprocess, urllib.request, urllib.error, statistics

API = "http://localhost:8000"
PG_NS = "abenix"; PG_POD = "abenix-postgresql-0"; DB = "abenix"; USER = "postgres"
PW = os.environ["PG_PASSWORD"]

def pg(sql, retries=3):
    for _ in range(retries):
        r = subprocess.run(
            ["kubectl", "exec", "-n", PG_NS, PG_POD, "--",
             "bash", "-c", f"PGPASSWORD='{PW}' psql -U {USER} -d {DB} -At -c \"{sql}\""],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        time.sleep(1)
    raise RuntimeError(f"pg failed: {r.stderr[:200]}")

def login():
    body = json.dumps({"email": "admin@abenix.dev", "password": "Admin123456"}).encode()
    req = urllib.request.Request(f"{API}/api/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["data"]["access_token"]

def hit(token, path):
    req = urllib.request.Request(f"{API}{path}",
        headers={"Authorization": f"Bearer {token}", "Connection": "close"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        try: e.read()
        except: pass
        return e.code, time.time() - t0
    except Exception:
        return -1, time.time() - t0

def xact():
    out = pg(f"SELECT xact_commit + xact_rollback FROM pg_stat_database WHERE datname='{DB}'")
    return int(out)

def baseline(seconds=30):
    print(f"[baseline {seconds}s no-load]")
    x0 = xact()
    time.sleep(seconds)
    x1 = xact()
    rate = (x1 - x0) / seconds
    print(f"  baseline_xps={rate:.2f}")
    return rate

def bench(path, n, token, bg_xps):
    # warm
    hit(token, path)
    time.sleep(3)
    x0 = xact()
    t0 = time.time()
    times = []
    codes = []
    for _ in range(n):
        c, t = hit(token, path)
        codes.append(c); times.append(t)
    elapsed = time.time() - t0
    time.sleep(3)
    x1 = xact()
    raw = x1 - x0
    bg = bg_xps * elapsed
    net = raw - bg
    avg_ms = statistics.mean(times) * 1000
    p95_ms = sorted(times)[int(len(times)*0.95)-1] * 1000
    print(f"  {path}: codes={set(codes)} n={n} elapsed={elapsed:.1f}s "
          f"avg={avg_ms:.0f}ms p95={p95_ms:.0f}ms "
          f"raw_xact={raw} bg_est={bg:.1f} net_xact={net:.1f} per_req={net/n:.2f}")
    return {"raw": raw, "net": net, "avg_ms": avg_ms, "elapsed": elapsed, "n": n}

def main():
    token = login()
    print(f"token_len={len(token)}")
    bg = baseline(30)
    print()
    results = {}
    # Run each twice, alternate, to control for ordering
    for round_i in (1, 2):
        print(f"=== round {round_i} ===")
        for path in ["/api/agents?limit=20", "/api/executions?limit=20"]:
            r = bench(path, 30, token, bg)
            results.setdefault(path, []).append(r)
        print()

    print("=== SUMMARY ===")
    for path, runs in results.items():
        avg_per_req = statistics.mean([r["net"]/r["n"] for r in runs])
        avg_lat = statistics.mean([r["avg_ms"] for r in runs])
        print(f"{path}: avg per_req={avg_per_req:.2f} xact, avg_latency={avg_lat:.0f}ms")

if __name__ == "__main__":
    main()
