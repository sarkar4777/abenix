"""Load test for Abenix API.

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host=http://localhost:8000
    # Then open http://localhost:8089 to configure and run
"""
from locust import HttpUser, task, between


class AbenixUser(HttpUser):
    wait_time = between(1, 3)
    token: str = ""

    def on_start(self):
        """Login and get access token."""
        res = self.client.post("/api/auth/login", json={
            "email": "admin@abenix.dev",
            "password": "Admin123456",
        })
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
        self.client.get("/api/analytics/summary", headers=self._headers())
