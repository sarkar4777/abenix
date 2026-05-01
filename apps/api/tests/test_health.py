from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["data"] == "Abenix API v0.1.0"
