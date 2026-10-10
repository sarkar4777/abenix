"""Workspace OIDC sign-in: URL mapping for dev, issuer guard, domains and ID token checks."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import types
import uuid

import pytest

from app.routers import sso_oidc as s


def _token(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.sig"


def test_url_map_both_ways(monkeypatch) -> None:
    monkeypatch.setenv(
        "OIDC_INTERNAL_URL_MAP",
        "http://localhost:8090=http://mock.ns.svc.cluster.local:8080",
    )
    assert s.to_internal("http://localhost:8090/default/token") == (
        "http://mock.ns.svc.cluster.local:8080/default/token"
    )
    assert s.to_public("http://mock.ns.svc.cluster.local:8080/default/authorize") == (
        "http://localhost:8090/default/authorize"
    )
    # a prefix of a longer port is not the mapped host
    assert s.to_internal("http://localhost:80901/x") == "http://localhost:80901/x"


def test_issuer_guard(monkeypatch) -> None:
    monkeypatch.delenv("EVENTS_ALLOW_PRIVATE_TARGETS", raising=False)
    monkeypatch.delenv("EVENTS_ALLOWED_INTERNAL_HOSTS", raising=False)
    monkeypatch.delenv("OIDC_INTERNAL_URL_MAP", raising=False)
    run = asyncio.run
    assert run(s.issuer_problem("not a url"))
    assert run(s.issuer_problem("http://93.184.216.34/realm"))
    assert run(s.issuer_problem("https://10.1.2.3/realm"))
    assert run(s.issuer_problem("https://127.0.0.1/realm"))
    assert run(s.issuer_problem("https://93.184.216.34/realm")) is None
    monkeypatch.setenv(
        "OIDC_INTERNAL_URL_MAP", "http://localhost:8090=http://mock:8080"
    )
    # only because an operator mapped it
    assert run(s.issuer_problem("http://localhost:8090/default")) is None


def test_domains_are_cleaned() -> None:
    got, bad = s.clean_domains([" Example.com ", "@acme.io", "example.com", ""])
    assert got == ["example.com", "acme.io"] and bad is None
    _, bad = s.clean_domains(["not a domain"])
    assert bad


def test_claims_are_read_from_the_id_token() -> None:
    claims = s._claims_of(_token({"sub": "u1", "email": "a@b.dev"}))
    assert claims["sub"] == "u1"
    with pytest.raises(s.SsoError):
        s._claims_of("garbage")


class _Resp:
    def __init__(self, code: int, body: dict):
        self.status_code = code
        self._body = body

    def json(self):
        return self._body


def _fake_http(token_body: dict, userinfo: dict):
    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data, headers):
            return _Resp(200, token_body)

        async def get(self, url, headers):
            return _Resp(200, userinfo)

    return C


def _setup(monkeypatch, claims: dict, userinfo: dict | None = None):
    issuer = "https://idp.example.com/realm"

    async def fake_discover(i, fresh=False):
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/auth",
            "token_endpoint": f"{issuer}/token",
            "userinfo_endpoint": f"{issuer}/userinfo",
        }

    monkeypatch.setattr(s, "discover", fake_discover)
    monkeypatch.setattr(
        s.httpx,
        "AsyncClient",
        _fake_http({"id_token": _token(claims), "access_token": "at"}, userinfo or {}),
    )
    cfg = {"issuer": issuer, "client_id": "abenix", "client_secret": "x"}
    tenant = types.SimpleNamespace(id=uuid.uuid4())
    return cfg, tenant


def test_exchange_accepts_a_good_token(monkeypatch) -> None:
    claims = {
        "iss": "https://idp.example.com/realm",
        "aud": "abenix",
        "sub": "123",
        "exp": int(time.time()) + 60,
        "nonce": "n1",
        "email": "Pat@Example.com",
        "name": "Pat Doe",
    }
    cfg, tenant = _setup(monkeypatch, claims)
    got = asyncio.run(s.exchange(cfg, tenant, "code", "n1", "acme"))
    assert got == {"sub": "123", "email": "pat@example.com", "name": "Pat Doe"}


@pytest.mark.parametrize(
    "change,needle",
    [
        ({"aud": "someone-else"}, "another application"),
        ({"iss": "https://evil.example.com"}, "different issuer"),
        ({"nonce": "other"}, "this browser"),
        ({"exp": 10}, "expired"),
        ({"email": ""}, "email address"),
        ({"email_verified": False}, "not verified"),
    ],
)
def test_exchange_refuses_bad_tokens(monkeypatch, change, needle) -> None:
    claims = {
        "iss": "https://idp.example.com/realm",
        "aud": "abenix",
        "sub": "123",
        "exp": int(time.time()) + 60,
        "nonce": "n1",
        "email": "pat@example.com",
        **change,
    }
    cfg, tenant = _setup(monkeypatch, claims)
    with pytest.raises(s.SsoError) as e:
        asyncio.run(s.exchange(cfg, tenant, "code", "n1", "acme"))
    assert needle in str(e.value)


def test_state_is_bound_to_the_workspace() -> None:
    st = s._sign_state("acme", "/dashboard", "n")
    assert s._read_state(st, "acme")["nonce"] == "n"
    assert s._read_state(st, "other") is None
    assert s._read_state("junk", "acme") is None
