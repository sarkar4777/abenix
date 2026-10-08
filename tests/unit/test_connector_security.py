"""Connector URL guard and write-only secrets, API side."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (
    ROOT / "apps" / "agent-runtime",
    ROOT / "apps" / "api",
    ROOT / "packages" / "db",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine import credentials, url_guard  # noqa: E402
from app.routers import connectors as router  # noqa: E402
from app.schemas.connectors import ConnectorCreate, ConnectorUpdate  # noqa: E402
from engine.tools.connector_call import resolve_secret, secret_key  # noqa: E402
from models.connector import Connector, ConnectorAuthType, ConnectorKind  # noqa: E402

T1 = uuid.uuid4()
T2 = uuid.uuid4()
SECRET = "sk-live-very-secret-9f8e7d"

PUBLIC = {"api.example.com": "93.184.216.34", "other.example.org": "93.184.216.35"}
PRIVATE = {"evil.example.com": "10.0.0.7", "rebind.example.com": "169.254.169.254"}


async def _fake_resolve(host: str, port: int) -> list[str]:
    ip = {**PUBLIC, **PRIVATE}.get(host)
    if ip is None:
        raise OSError("name does not resolve")
    return [ip]


class RecordingDB:
    def __init__(self):
        self.statements: list[tuple[str, dict]] = []
        self.added: list = []
        self.deleted: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.statements.append((" ".join(str(stmt).split()), dict(params or {})))

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _user(tenant=T1):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant)


def _connector(tenant=T1, **kw) -> Connector:
    base = dict(
        id=uuid.uuid4(),
        tenant_id=tenant,
        name="Acme",
        kind=ConnectorKind.cmms,
        preset_key=None,
        base_url="https://api.example.com/v1",
        auth_type=ConnectorAuthType.bearer,
        secret_ref=None,
        config={},
        is_active=True,
    )
    base.update(kw)
    return Connector(**base)


def _body(resp) -> dict:
    return json.loads(resp.body)


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


def _mock_http(monkeypatch, handler):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(
        router,
        "_http_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(wrapped), follow_redirects=False
        ),
    )
    return calls


def _use(monkeypatch, c: Connector, keys: set[str] | None = None):
    async def load(db, cid, tid):
        return c if (c.id == cid and c.tenant_id == tid) else None

    async def secret_keys(db, tid):
        return keys or set()

    monkeypatch.setattr(router, "_load", load)
    monkeypatch.setattr(router, "_secret_keys", secret_keys)


# --- the guard ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/api",
        "http://127.0.0.1:8000/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://2130706433/",
        "http://localhost:8000/",
    ],
)
@pytest.mark.asyncio
async def test_guard_refuses_private_addresses(url):
    assert await url_guard.check(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://abenix-api.abenix.svc.cluster.local:8000/api",
        "http://redis.default.svc/",
        "http://kubernetes.default/",
        "http://metadata.google.internal/",
    ],
)
@pytest.mark.asyncio
async def test_guard_refuses_cluster_dns(url):
    reason = await url_guard.check(url)
    assert reason is not None


@pytest.mark.asyncio
async def test_guard_refuses_a_name_that_resolves_private():
    reason = await url_guard.check("https://evil.example.com/x")
    assert reason and "private address" in reason


@pytest.mark.asyncio
async def test_guard_allows_public_and_rejects_other_schemes():
    assert await url_guard.check("https://api.example.com/v1") is None
    assert await url_guard.check("ftp://api.example.com/") is not None
    assert await url_guard.check("file:///etc/passwd") is not None


@pytest.mark.asyncio
async def test_guard_unresolvable_only_passes_when_not_required():
    assert await url_guard.check("https://{instance}.service-now.com/api") is not None
    assert (
        await url_guard.check(
            "https://{instance}.service-now.com/api", require_dns=False
        )
        is None
    )


@pytest.mark.asyncio
async def test_guard_opt_in_allows_private():
    assert await url_guard.check("http://10.0.0.5/", allow_private=True) is None
    assert await url_guard.check("gopher://10.0.0.5/", allow_private=True) is not None


# --- create and update -------------------------------------------------------


@pytest.mark.asyncio
async def test_create_rejects_a_private_base_url():
    db = RecordingDB()
    body = ConnectorCreate(name="x", kind="cmms", base_url="http://10.1.2.3/api")
    resp = await router.create_connector(body, user=_user(), db=db)
    assert resp.status_code == 400
    assert "blocked" in _body(resp)["error"]["message"].lower()
    assert db.added == []


@pytest.mark.asyncio
async def test_create_rejects_cluster_dns():
    body = ConnectorCreate(
        name="x", kind="cmms", base_url="http://abenix-api.abenix.svc.cluster.local/"
    )
    resp = await router.create_connector(body, user=_user(), db=RecordingDB())
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_keeps_a_preset_template_that_does_not_resolve_yet():
    body = ConnectorCreate(
        name="x", kind="cmms", base_url="https://{instance}.service-now.com/api/now"
    )
    resp = await router.create_connector(body, user=_user(), db=RecordingDB())
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_create_allows_private_with_the_opt_in(monkeypatch):
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", "true")
    body = ConnectorCreate(name="x", kind="cmms", base_url="http://10.1.2.3/api")
    resp = await router.create_connector(body, user=_user(), db=RecordingDB())
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_update_rejects_a_private_base_url(monkeypatch):
    c = _connector()
    _use(monkeypatch, c)
    resp = await router.update_connector(
        c.id,
        ConnectorUpdate(base_url="http://192.168.1.1/"),
        user=_user(),
        db=RecordingDB(),
    )
    assert resp.status_code == 400
    assert c.base_url == "https://api.example.com/v1"


# --- secrets -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_stores_the_secret_and_never_returns_it():
    db = RecordingDB()
    body = ConnectorCreate(
        name="x",
        kind="cmms",
        base_url="https://api.example.com/v1",
        auth_type="bearer",
        secret=SECRET,
    )
    resp = await router.create_connector(body, user=_user(), db=db)
    assert resp.status_code == 201
    raw = resp.body.decode()
    assert SECRET not in raw
    data = _body(resp)["data"]
    assert data["has_secret"] is True and data["needs_secret"] is False
    assert "secret" not in data and "secret_ref" not in data
    inserts = [
        p for s, p in db.statements if "INSERT INTO tenant_tool_credentials" in s
    ]
    assert len(inserts) == 1
    assert inserts[0]["tid"] == str(T1)
    assert inserts[0]["key"] == secret_key(db.added[0].id)


@pytest.mark.asyncio
async def test_list_and_get_only_say_has_secret(monkeypatch):
    c = _connector()
    _use(monkeypatch, c, {secret_key(c.id)})
    credentials._tenant_snapshot[(str(T1), secret_key(c.id))] = SECRET
    resp = await router.get_connector(c.id, user=_user(), db=RecordingDB())
    assert SECRET not in resp.body.decode()
    assert _body(resp)["data"]["has_secret"] is True


@pytest.mark.asyncio
async def test_update_replaces_and_clears_the_secret(monkeypatch):
    c = _connector(secret_ref=uuid.uuid4())
    _use(monkeypatch, c)
    db = RecordingDB()
    resp = await router.update_connector(
        c.id, ConnectorUpdate(secret="new-one"), user=_user(), db=db
    )
    assert "new-one" not in resp.body.decode()
    assert any("INSERT INTO tenant_tool_credentials" in s for s, _ in db.statements)
    assert c.secret_ref is None

    db = RecordingDB()
    await router.update_connector(
        c.id, ConnectorUpdate(clear_secret=True), user=_user(), db=db
    )
    deletes = [
        p for s, p in db.statements if "DELETE FROM tenant_tool_credentials" in s
    ]
    assert deletes == [{"tid": str(T1), "key": secret_key(c.id)}]


@pytest.mark.asyncio
async def test_delete_removes_the_stored_secret(monkeypatch):
    c = _connector()
    _use(monkeypatch, c)
    db = RecordingDB()
    resp = await router.delete_connector(c.id, user=_user(), db=db)
    assert resp.status_code == 200
    deletes = [
        p for s, p in db.statements if "DELETE FROM tenant_tool_credentials" in s
    ]
    assert deletes == [{"tid": str(T1), "key": secret_key(c.id)}]
    assert db.deleted == [c]


def test_legacy_ref_shows_needs_secret():
    c = _connector(secret_ref=uuid.uuid4())
    out = router._serialize(c, has_secret=False)
    assert out["needs_secret"] is True
    assert out["secret_notice"] == (
        "Re-enter this connector's secret, it used to point at an Abenix API key"
    )
    assert router._serialize(c, has_secret=True)["needs_secret"] is False


@pytest.mark.asyncio
async def test_legacy_ref_is_never_sent(monkeypatch):
    c = _connector(secret_ref=uuid.uuid4())
    _use(monkeypatch, c)
    calls = _mock_http(monkeypatch, lambda r: httpx.Response(200))
    resp = await router.test_connector(c.id, user=_user(), db=RecordingDB())
    data = _body(resp)["data"]
    assert calls == []
    assert data["ok"] is False
    assert "Re-enter this connector's secret" in data["message"]


@pytest.mark.asyncio
async def test_secret_is_scoped_to_the_connectors_tenant():
    cid = uuid.uuid4()
    credentials._tenant_snapshot[(str(T1), secret_key(cid))] = SECRET
    assert await resolve_secret(cid, T1) == SECRET
    assert await resolve_secret(cid, T2) == ""
    assert await resolve_secret(cid, "") == ""


@pytest.mark.asyncio
async def test_test_sends_the_stored_secret(monkeypatch):
    c = _connector()
    _use(monkeypatch, c)
    credentials._tenant_snapshot[(str(T1), secret_key(c.id))] = SECRET
    calls = _mock_http(monkeypatch, lambda r: httpx.Response(200, text="hi"))
    resp = await router.test_connector(c.id, user=_user(), db=RecordingDB())
    assert _body(resp)["data"]["ok"] is True
    assert calls[0].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in resp.body.decode()


@pytest.mark.asyncio
async def test_other_tenant_cannot_test_the_connector(monkeypatch):
    c = _connector()
    _use(monkeypatch, c)
    resp = await router.test_connector(c.id, user=_user(T2), db=RecordingDB())
    assert resp.status_code == 404


# --- test results ------------------------------------------------------------


@pytest.mark.parametrize(
    "status,ok",
    [
        (200, True),
        (204, True),
        (301, True),
        (304, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (429, False),
        (500, False),
        (503, False),
    ],
)
def test_ok_only_on_2xx_and_3xx(status, ok):
    assert router.describe_status(status, 10)[0] is ok


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_refused_credentials_message(monkeypatch, status):
    c = _connector()
    _use(monkeypatch, c)
    _mock_http(monkeypatch, lambda r: httpx.Response(status))
    data = _body(await router.test_connector(c.id, user=_user(), db=RecordingDB()))[
        "data"
    ]
    assert data["ok"] is False
    assert "refused the credentials" in data["message"]
    assert c.last_test_ok is False


@pytest.mark.asyncio
async def test_test_blocks_a_private_base_url(monkeypatch):
    c = _connector(base_url="http://10.0.0.9/")
    _use(monkeypatch, c)
    calls = _mock_http(monkeypatch, lambda r: httpx.Response(200))
    data = _body(await router.test_connector(c.id, user=_user(), db=RecordingDB()))[
        "data"
    ]
    assert calls == []
    assert data["blocked"] is True and data["ok"] is False
    assert data["message"].startswith("Blocked: ")


@pytest.mark.asyncio
async def test_test_blocks_a_redirect_to_a_private_address(monkeypatch):
    c = _connector()
    _use(monkeypatch, c)
    credentials._tenant_snapshot[(str(T1), secret_key(c.id))] = SECRET

    def handler(r):
        return httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest"}
        )

    calls = _mock_http(monkeypatch, handler)
    data = _body(await router.test_connector(c.id, user=_user(), db=RecordingDB()))[
        "data"
    ]
    assert len(calls) == 1
    assert data["blocked"] is True
    assert "after a redirect" in data["message"]


@pytest.mark.asyncio
async def test_test_follows_at_most_three_redirects(monkeypatch):
    c = _connector()
    _use(monkeypatch, c)
    calls = _mock_http(
        monkeypatch,
        lambda r: httpx.Response(
            302, headers={"location": "https://api.example.com/loop"}
        ),
    )
    data = _body(await router.test_connector(c.id, user=_user(), db=RecordingDB()))[
        "data"
    ]
    assert len(calls) == 4
    assert data["ok"] is False
    assert "more than 3 times" in data["message"]


@pytest.mark.asyncio
async def test_redirect_to_another_host_drops_the_secret(monkeypatch):
    c = _connector(auth_type=ConnectorAuthType.api_key)
    _use(monkeypatch, c)
    credentials._tenant_snapshot[(str(T1), secret_key(c.id))] = SECRET

    def handler(r):
        if r.url.host == "api.example.com":
            return httpx.Response(
                302, headers={"location": "https://other.example.org/"}
            )
        return httpx.Response(200)

    calls = _mock_http(monkeypatch, handler)
    data = _body(await router.test_connector(c.id, user=_user(), db=RecordingDB()))[
        "data"
    ]
    assert data["ok"] is True
    assert calls[0].headers["x-api-key"] == SECRET
    assert "x-api-key" not in calls[1].headers


@pytest.mark.asyncio
async def test_test_allows_private_with_the_opt_in(monkeypatch):
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_TARGETS", "1")
    c = _connector(base_url="http://10.0.0.9/")
    _use(monkeypatch, c)
    calls = _mock_http(monkeypatch, lambda r: httpx.Response(200))
    data = _body(await router.test_connector(c.id, user=_user(), db=RecordingDB()))[
        "data"
    ]
    assert len(calls) == 1 and data["ok"] is True
