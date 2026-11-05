"""Load test for Abenix API.

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host=http://localhost:8000
    # Then open http://localhost:8089 to configure and run

Exits 0 when every threshold holds, 1 when one fails, 2 when nothing succeeded or a limit is not a number.
Limits come from LOCUST_MAX_FAIL_RATIO, LOCUST_MAX_P95_MS and LOCUST_MIN_RPS. 0 turns off the last two.
"""

import os

from locust import HttpUser, between, events, task
from locust.runners import WorkerRunner


def check(name, measured, limit, ceiling=True):
    ok = measured <= limit if ceiling else measured >= limit
    print(
        f"{'PASS' if ok else 'FAIL'} {name} measured={measured} limit={limit}",
        flush=True,
    )
    return ok


def evaluate(requests, failures, p95_ms, rps, max_fail_ratio, max_p95_ms, min_rps):
    if requests - failures <= 0:
        print(f"no successful requests, {failures} failed", flush=True)
        return 2
    results = [check("fail_ratio", round(failures / requests, 4), max_fail_ratio)]
    if max_p95_ms > 0:
        results.append(check("p95_ms", p95_ms, max_p95_ms))
    if min_rps > 0:
        results.append(check("rps", round(rps, 2), min_rps, ceiling=False))
    return 0 if all(results) else 1


@events.quitting.add_listener
def set_exit_code(environment, **_kwargs):
    if isinstance(environment.runner, WorkerRunner):
        return
    try:
        limits = (
            float(os.environ.get("LOCUST_MAX_FAIL_RATIO") or 0.05),
            float(os.environ.get("LOCUST_MAX_P95_MS") or 3000),
            float(os.environ.get("LOCUST_MIN_RPS") or 0.2),
        )
    except ValueError as exc:
        print(f"a LOCUST_ threshold is not a number, {exc}", flush=True)
        environment.process_exit_code = 2
        return
    total = environment.stats.total
    environment.process_exit_code = evaluate(
        total.num_requests,
        total.num_failures,
        total.get_response_time_percentile(0.95) or 0,
        total.total_rps,
        *limits,
    )


class AbenixUser(HttpUser):
    wait_time = between(1, 3)
    token: str = ""

    def on_start(self):
        """Login and get access token."""
        res = self.client.post(
            "/api/auth/login",
            json={
                "email": "admin@abenix.dev",
                "password": "Admin123456",
            },
        )
        data = res.json().get("data", {})
        self.token = data.get("access_token", "")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    @task(5)
    def health_check(self):
        self.client.get("/api/health")

    @task(3)
    def readiness_check(self):
        self.client.get("/api/health/ready")

    @task(5)
    def list_agents(self):
        self.client.get("/api/agents", headers=self._headers())

    @task(2)
    def get_profile(self):
        self.client.get("/api/settings/profile", headers=self._headers())

    @task(1)
    def list_executions(self):
        self.client.get("/api/executions?limit=10", headers=self._headers())

    @task(1)
    def list_conversations(self):
        self.client.get("/api/conversations?limit=10", headers=self._headers())

    @task(1)
    def analytics(self):
        self.client.get("/api/analytics/overview", headers=self._headers())
