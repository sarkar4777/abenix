# Load test baseline

A small, reproducible smoke load test that anyone can run against any Abenix deployment. The goal is not to set records, it's to make regressions obvious.

## What it measures

| Surface | Workload | What good looks like |
|---|---|---|
| `GET /api/health/ready` | 100 req/s for 60s, 1 connection | p99 < 50ms, error rate 0% |
| `POST /api/auth/login` | 20 req/s for 30s | p95 < 250ms, error rate 0% |
| `GET /api/agents` (authed) | 50 req/s for 60s | p99 < 200ms, error rate 0% |
| Agent execute end-to-end | 5 concurrent runs, simple agent, haiku model | p95 < 6s, error rate 0% |

## How to run it

```bash
# Install k6 if you don't have it
# https://k6.io/docs/get-started/installation/

# Run against any base URL
BASE=https://api.your-deploy.com k6 run scripts/load/baseline.js
```

## Reading the results

k6 prints `iteration_duration` percentiles and `http_req_duration` percentiles. If any threshold listed in the script fails, k6 exits non-zero. CI / on-demand operators can pipe this through their alerting.

## Last recorded numbers (single-node minikube, 8 vCPU, 16GB RAM)

| Surface | p50 | p95 | p99 | err |
|---|---|---|---|---|
| `/health/ready` | 4ms | 12ms | 28ms | 0% |
| `/auth/login` | 87ms | 142ms | 198ms | 0% |
| `/agents` | 32ms | 88ms | 134ms | 0% |
| agent execute (haiku, no tools) | 1.4s | 2.8s | 4.1s | 0% |

These are baseline numbers, not SLAs. They exist so the next person who runs the test can spot "x feature got 3x slower" without having to know the absolute target.

## What this test does NOT cover

- Long-running pipelines (the `long-running` pool serves those, and they're slow by design — measuring their p95 over short windows is misleading).
- Real LLM cost / token spend — the script uses a cheap-by-design agent.
- Sustained throughput over hours — for capacity planning, lengthen `duration` and watch DB connection saturation and Redis stream backlog separately.
- Cross-region latency — run from the same region you're testing.

## Reference: extending the test

If you add a new high-traffic endpoint, append a scenario in `scripts/load/baseline.js`. Keep total k6 runtime under 5 minutes so the test stays cheap to run.
