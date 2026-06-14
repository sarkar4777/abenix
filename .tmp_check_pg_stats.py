import os
import subprocess
import time
import json
import urllib.request

API = "http://localhost:8000"
PG_NS = "abenix"
PG_POD = "abenix-postgresql-0"
DB_NAME = "abenix"
DB_USER = "postgres"
PG_PASSWORD = os.environ["PG_PASSWORD"]


def pg(sql: str) -> str:
    cmd = [
        "kubectl", "exec", "-n", PG_NS, PG_POD, "--",
        "bash", "-c",
        f"PGPASSWORD='{PG_PASSWORD}' psql -U {DB_USER} -d {DB_NAME} -At -c \"{sql}\"",
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
        return json.loads(r.read())["data"]["access_token"]


def hit(token, path):
    req = urllib.request.Request(
        f"{API}{path}", headers={"Authorization": f"Bearer {token}", "Connection": "close"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        try: e.read()
        except Exception: pass
        return e.code, time.time() - t0
    except Exception as e:
        return -1, time.time() - t0


# Check pg_stat_statements
ext = pg("SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
print(f"pg_stat_statements_installed={ext}")

token = login()
print(f"token_len={len(token)}")

# Get current xact_commit + total query count
def snap():
    out = pg("SELECT xact_commit, xact_rollback, blks_read, blks_hit, tup_returned, tup_fetched FROM pg_stat_database WHERE datname='abenix'")
    parts = out.split("|")
    return {"xact_commit": int(parts[0]), "xact_rollback": int(parts[1]), "blks_read": int(parts[2]), "blks_hit": int(parts[3]), "tup_returned": int(parts[4]), "tup_fetched": int(parts[5])}

# Idle baseline
print("\n=== IDLE BASELINE (15s, no requests) ===")
s0 = snap()
time.sleep(15)
s1 = snap()
for k in s0: print(f"  {k}: +{s1[k] - s0[k]}")
bg_xact_per_s = (s1["xact_commit"] - s0["xact_commit"] + s1["xact_rollback"] - s0["xact_rollback"]) / 15.0
print(f"  bg_xact_per_s={bg_xact_per_s:.2f}")

# Burst /api/agents
print("\n=== /api/agents x 30 ===")
hit(token, "/api/agents?limit=20")  # warm
time.sleep(2)
s0 = snap()
t0 = time.time()
codes = []
times = []
for _ in range(30):
    c, t = hit(token, "/api/agents?limit=20")
    codes.append(c); times.append(t)
elapsed = time.time() - t0
time.sleep(2)
s1 = snap()
for k in s0:
    delta = s1[k] - s0[k]
    raw_per_req = delta / 30
    print(f"  {k}: total={delta} per_req_raw={raw_per_req:.2f}")
raw_xact = (s1["xact_commit"] - s0["xact_commit"]) + (s1["xact_rollback"] - s0["xact_rollback"])
bg_est = bg_xact_per_s * elapsed
print(f"  elapsed={elapsed:.2f}s avg_latency_ms={sum(times)/len(times)*1000:.0f}")
print(f"  raw_xact={raw_xact} bg_est={bg_est:.1f} net_xact={(raw_xact-bg_est):.1f} per_req_net={(raw_xact-bg_est)/30:.2f}")

# Burst /api/executions
print("\n=== /api/executions x 30 ===")
hit(token, "/api/executions?limit=20")
time.sleep(2)
s0 = snap()
t0 = time.time()
codes = []
times = []
for _ in range(30):
    c, t = hit(token, "/api/executions?limit=20")
    codes.append(c); times.append(t)
elapsed = time.time() - t0
time.sleep(2)
s1 = snap()
for k in s0:
    delta = s1[k] - s0[k]
    print(f"  {k}: total={delta} per_req_raw={delta/30:.2f}")
raw_xact = (s1["xact_commit"] - s0["xact_commit"]) + (s1["xact_rollback"] - s0["xact_rollback"])
bg_est = bg_xact_per_s * elapsed
print(f"  elapsed={elapsed:.2f}s avg_latency_ms={sum(times)/len(times)*1000:.0f}")
print(f"  raw_xact={raw_xact} bg_est={bg_est:.1f} net_xact={(raw_xact-bg_est):.1f} per_req_net={(raw_xact-bg_est)/30:.2f}")

# What does /api/agents return?
print("\n=== /api/agents response shape ===")
import urllib.request
req = urllib.request.Request(f"{API}/api/agents?limit=20", headers={"Authorization": f"Bearer {token}"})
with urllib.request.urlopen(req) as r:
    d = json.loads(r.read())
print(f"  count={len(d.get('data', []))} total={d.get('meta', {}).get('total')}")
