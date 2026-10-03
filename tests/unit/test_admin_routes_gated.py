"""Every /api/admin route refuses a signed-in user who is not an admin."""

from __future__ import annotations

import importlib
import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.deps import get_current_user, get_db
from models.user import UserRole

ADMIN_ROUTER_MODULES = [
    "admin_alerts",
    "admin_cluster",
    "admin_dlq",
    "admin_model_availability",
    "admin_pricing",
    "admin_scaling",
    "admin_settings",
    "admin_tool_config",
    "archives",
    "notifications",
    "tool_runtime",
]

# Open on purpose: the model list any signed-in user can pick from, and the
# Alertmanager webhook which authenticates with its own shared token.
PUBLIC_ADMIN_ROUTES = {
    ("GET", "/api/admin/settings/models/public"),
    ("POST", "/api/admin/alerts/webhook"),
}


class _NoDB:
    async def execute(self, *a, **k):
        raise AssertionError("non-admin request reached the database")

    async def commit(self):
        raise AssertionError("non-admin request reached the database")

    def add(self, *_):
        raise AssertionError("non-admin request reached the database")


def _app() -> FastAPI:
    app = FastAPI()
    for name in ADMIN_ROUTER_MODULES:
        app.include_router(importlib.import_module(f"app.routers.{name}").router)
    member = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="member@example.com",
        role=UserRole.USER,
        is_admin=False,
    )

    async def _user():
        return member

    async def _db():
        yield _NoDB()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return app


def _admin_routes(app: FastAPI):
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/admin"):
            continue
        for method in route.methods:
            if (method, route.path) not in PUBLIC_ADMIN_ROUTES:
                yield method, route.path


APP = _app()
ROUTES = sorted(set(_admin_routes(APP)))


def test_sweep_covers_the_reported_routes():
    paths = {p for _, p in ROUTES}
    assert "/api/admin/tool-runtime" in paths
    assert "/api/admin/tool-runtime/{slug}" in paths
    assert "/api/admin/scaling/pipelines" in paths


@pytest.mark.parametrize("method,path", ROUTES)
def test_non_admin_gets_403(method, path):
    url = re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)
    client = TestClient(APP, raise_server_exceptions=False)
    kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
    resp = client.request(method, url, **kwargs)
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"
