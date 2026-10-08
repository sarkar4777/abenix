"""connector_call uses the stored secret and refuses private targets."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from engine import credentials, url_guard
from engine.tools import connector_call as cc

T1 = str(uuid.uuid4())
T2 = str(uuid.uuid4())
SECRET = "sk-live-runtime-1234"


async def _fake_resolve(host: str, port: int) -> list[str]:
    table = {"api.example.com": "93.184.216.34", "evil.example.com": "10.9.8.7"}
    if host not in table:
        raise OSError("no such host")
    return [table[host]]


def _row(**kw):
    base = {
        "id": str(uuid.uuid4()),
        "tenant_id": T1,
        "preset_key": "weather_dtn",
        "base_url": "https://api.example.com/weather/v1",
        "auth_type": "bearer",
        "config": {},
        "legacy_ref": False,
        "is_active": True,
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", raising=False)
    monkeypatch.setattr(url_guard, "_resolve", _fake_resolve)
    credentials.configure(loader=None, ttl=30)
    credentials._snapshot.clear()
    credentials._tenant_snapshot.clear()

    async def _no_refresh(force: bool = False):
        return None

    monkeypatch.setattr(credentials, "ensure_fresh", _no_refresh)
    yield
    credentials._snapshot.clear()
    credentials._tenant_snapshot.clear()


def _wire(monkeypatch, row, handler):
    calls: list[httpx.Request] = []

    async def load(self, connector_id):
        return row

    def wrapped(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(cc.ConnectorCallTool, "_load", load)
    monkeypatch.setattr(
        cc,
        "_http_client",
        lambda timeout: httpx.AsyncClient(
            transport=httpx.MockTransport(wrapped), follow_redirects=False
        ),
    )
    return calls


async def _call(row):
    return await cc.ConnectorCallTool().execute(
        {
            "connector_id": row["id"],
            "operation": "get_forecast",
            "parameters": {"lat": 1, "lon": 2, "hours": 24},
        }
    )


@pytest.mark.asyncio
async def test_sends_the_stored_secret(monkeypatch):
    row = _row()
    credentials._tenant_snapshot[(T1, cc.secret_key(row["id"]))] = SECRET
    calls = _wire(monkeypatch, row, lambda r: httpx.Response(200, json={"ok": 1}))
    res = await _call(row)
    assert not res.is_error, res.content
    assert calls[0].headers["authorization"] == f"Bearer {SECRET}"
    assert json.loads(res.content)["ok"] is True


@pytest.mark.asyncio
async def test_secret_of_another_tenant_is_not_used(monkeypatch):
    row = _row(tenant_id=T2)
    credentials._tenant_snapshot[(T1, cc.secret_key(row["id"]))] = SECRET
    calls = _wire(monkeypatch, row, lambda r: httpx.Response(200, json={}))
    await _call(row)
    assert "authorization" not in calls[0].headers


@pytest.mark.asyncio
async def test_legacy_api_key_ref_is_never_sent(monkeypatch):
    row = _row(legacy_ref=True)
    calls = _wire(monkeypatch, row, lambda r: httpx.Response(200, json={}))
    res = await _call(row)
    assert res.is_error
    assert calls == []
    assert "Re-enter this connector's secret" in res.content


@pytest.mark.asyncio
async def test_refuses_a_private_base_url(monkeypatch):
    row = _row(base_url="http://10.0.0.4/api")
    calls = _wire(monkeypatch, row, lambda r: httpx.Response(200, json={}))
    res = await _call(row)
    assert res.is_error and calls == []
    body = json.loads(res.content)
    assert body["blocked"] is True
    assert body["response_body"]["error"].startswith("Blocked: ")


@pytest.mark.asyncio
async def test_refuses_cluster_dns_and_names_that_resolve_private(monkeypatch):
    for base in (
        "http://abenix-api.abenix.svc.cluster.local:8000",
        "https://evil.example.com/v1",
    ):
        calls = _wire(monkeypatch, _row(base_url=base), lambda r: httpx.Response(200))
        res = await _call(_row(base_url=base))
        assert res.is_error and calls == []


@pytest.mark.asyncio
async def test_refuses_a_redirect_to_a_private_address(monkeypatch):
    row = _row()
    credentials._tenant_snapshot[(T1, cc.secret_key(row["id"]))] = SECRET
    calls = _wire(
        monkeypatch,
        row,
        lambda r: httpx.Response(307, headers={"location": "http://127.0.0.1:6379/"}),
    )
    res = await _call(row)
    assert res.is_error and len(calls) == 1
    assert json.loads(res.content)["blocked"] is True


@pytest.mark.asyncio
async def test_private_target_allowed_with_the_opt_in(monkeypatch):
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", "true")
    row = _row(base_url="http://10.0.0.4/api")
    calls = _wire(monkeypatch, row, lambda r: httpx.Response(200, json={}))
    res = await _call(row)
    assert not res.is_error and len(calls) == 1


def test_secret_key_shape():
    cid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert cc.secret_key(cid) == "CONNECTOR_12345678123456781234567812345678_SECRET"
