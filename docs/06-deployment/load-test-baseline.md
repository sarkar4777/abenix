# Load test baseline

A small, reproducible smoke load test that anyone can run against any Abenix deployment. The goal is not to set records, it's to make regressions obvious.

## What it measures

`scripts/load/baseline.js` runs three k6 scenarios one after another, about
three minutes in all:

| Surface | Workload | Threshold in the script |
|---|---|---|
| `GET /api/health/ready` | 100 req/s for 60s | p99 < 100ms |
| `POST /api/auth/login` | 20 req/s for 30s, starting at 70s | p95 < 400ms |
| `GET /api/agents` (authed) | 50 req/s for 60s, starting at 110s | p99 < 400ms |

Across all of them `http_req_failed` must stay under 1%. Agent execution is not
part of this script.

## How to run it

```bash
# Install k6 if you don't have it
# https://k6.io/docs/get-started/installation/

# BASE is the API base. EMAIL and PASSWORD default to the seeded admin
BASE=https://api.your-deploy.com k6 run scripts/load/baseline.js
```

The login scenario counts against the auth rate limit, 30 a minute per IP by
default. Run against a deploy with `IS_LOCAL_DEV=1`, or raise
`RATE_LIMIT_AUTH_REQ_PER_MIN`, or the thresholds fail on 429s.

## Reading the results

k6 prints `iteration_duration` percentiles and `http_req_duration` percentiles. If any threshold listed in the script fails, k6 exits non-zero. CI / on-demand operators can pipe this through their alerting.

## Last recorded numbers (single-node minikube, 8 vCPU, 16GB RAM)

| Surface | p50 | p95 | p99 | err |
|---|---|---|---|---|
| `/health/ready` | 4ms | 12ms | 28ms | 0% |
| `/auth/login` | 87ms | 142ms | 198ms | 0% |
| `/agents` | 32ms | 88ms | 134ms | 0% |

These are baseline numbers, not SLAs. They exist so the next person who runs the test can spot "x feature got 3x slower" without having to know the absolute target.

## 2.5.2: decision evaluation

`POST /api/decisions/{key}/evaluate` under sustained concurrency, with a new version published partway through the run.

Setup: minikube, one API pod with 2 CPU and 2 uvicorn workers (`API_WORKERS=2`). Load generated from a pod inside the cluster.

| Concurrent users | Requests/s | p50 | p95 | Errors |
|---|---|---|---|---|
| 200 | 1,467 | 112 ms | 279 ms | 0 |
| 500 | 1,306 | 298 ms | 525 ms | 0 |
| 2,000 | 1,096 | 613 ms | 8.6 s | 41 transport errors (0.07%), no 401 or 500 |

A publish mid-run switched versions with zero nondeterministic cases. Every set of facts gave one trace hash per version.

Latency at high concurrency is requests queueing on a single pod, not slow evaluation. Throughput peaked at 200 users and held near it as users grew. For more users, scale API replicas.

### How to run it

Run both scripts from a pod inside the cluster. Going through a port-forward measures the forward.

```bash
# creates a decision with v1 in force and v2 approved, prints {"key": ..., "token": ...}
BASE=http://abenix-api:8000 AF_EMAIL=admin@abenix.dev AF_PASSWORD=...   python scripts/load/decision_load_setup.py

python scripts/load/decision_load.py --base http://abenix-api:8000   --token <token> --key <key>   --concurrency 500 --seconds 60 --publish-at 20 --publish-version 2
```

| Flag | Default | Notes |
|---|---|---|
| `--concurrency` | `500` | Open connections, one worker each |
| `--seconds` | `60` | Run length |
| `--publish-at` | `0` | Seconds in to publish. 0 means no publish |
| `--publish-version` | `0` | Version to publish |
| `--procs` | `0` | Worker processes. 0 means one per 32 connections |

The load is spread over processes because one httpx client degrades past a few dozen connections and the client becomes the bottleneck. The script prints one JSON line with `rps`, `p50_ms`, `p95_ms`, `p99_ms`, `errors` by status or exception, `versions_seen` and `nondeterministic_cases`. Anything above 0 in the last one is a bug.

## What this test does NOT cover

- Long-running pipelines (the `long-running` pool serves those, and they're slow by design — measuring their p95 over short windows is misleading).
- Agent runs and LLM spend — the script never starts a run.
- Sustained throughput over hours — for capacity planning, lengthen `duration` and watch DB connection saturation and Redis stream backlog separately.
- Cross-region latency — run from the same region you're testing.

## Other benchmarks in `scripts/load/`

| Script | What it measures | Where to run it |
|---|---|---|
| `code_runner_bench.py` | Cold, warm, scale-from-zero, new-version and concurrent latency of one code asset through the real `code_asset` tool | Inside an agent-runtime pod, see its docstring |
| `middleware_bench.py` | The API middleware stack in process, `--requests` and `--concurrency` | Anywhere with the API dependencies installed |

## Reference: extending the test

If you add a new high-traffic endpoint, append a scenario in `scripts/load/baseline.js`. Keep total k6 runtime under 5 minutes so the test stays cheap to run.
