"""Sessions, password reset tokens, two-step sign-in codes and the sign-in helpers."""

from __future__ import annotations

import base64
import time
import types
import uuid

import pytest

from app.core import totp, two_factor
from app.core.security import (
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    verify_password,
    verify_token,
)

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def test_totp_matches_rfc6238_vector() -> None:
    # RFC 6238 appendix B, SHA1 at T=59 is 94287082, the last 6 digits
    assert totp.code_at(RFC_SECRET, 59 // 30) == "287082"
    assert totp.code_at(RFC_SECRET, 1111111109 // 30) == "081804"


def test_totp_allows_one_step_of_drift_and_refuses_replay() -> None:
    now = 1_700_000_000.0
    step = totp.current_step(now)
    code = totp.code_at(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code, now=now) == step
    prev = totp.code_at(RFC_SECRET, step - 1)
    assert totp.verify(RFC_SECRET, prev, now=now) == step - 1
    old = totp.code_at(RFC_SECRET, step - 3)
    assert totp.verify(RFC_SECRET, old, now=now) is None
    # used once, the same code cannot sign in again
    assert totp.verify(RFC_SECRET, code, last_step=step, now=now) is None
    assert totp.verify(RFC_SECRET, "12 34", now=now) is None
    assert totp.verify(RFC_SECRET, f"{code[:3]} {code[3:]}", now=now) == step


def test_otpauth_uri_names_issuer_and_account() -> None:
    uri = totp.otpauth_uri("ABC", "a@b.dev")
    assert uri.startswith("otpauth://totp/Abenix%3Aa%40b.dev?secret=ABC")
    assert "issuer=Abenix" in uri and "digits=6" in uri


def _user(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        totp_secret=None,
        totp_last_step=None,
        totp_recovery_codes=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_two_factor_check_code_app_then_recovery_once(monkeypatch) -> None:
    monkeypatch.delenv("ABENIX_DATA_KEY_KEK_BASE64", raising=False)
    u = _user()
    secret = totp.new_secret()
    two_factor.store_secret(u, secret)
    assert two_factor.secret_of(u) == secret
    code = totp.code_at(secret, totp.current_step())
    assert two_factor.check_code(u, code) == "app"
    assert two_factor.check_code(u, code) is None

    codes = two_factor.issue_recovery_codes(u)
    assert len(codes) == 8 and len(u.totp_recovery_codes) == 8
    assert codes[0] not in u.totp_recovery_codes
    assert two_factor.check_code(u, codes[0].upper()) == "recovery"
    assert two_factor.check_code(u, codes[0]) is None
    assert len(u.totp_recovery_codes) == 7


def test_two_factor_secret_is_encrypted_with_a_kek(monkeypatch) -> None:
    monkeypatch.setenv(
        "ABENIX_DATA_KEY_KEK_BASE64", base64.b64encode(b"k" * 32).decode()
    )
    u = _user()
    two_factor.store_secret(u, "JBSWY3DPEHPK3PXP")
    assert u.totp_secret.startswith("v1:")
    assert two_factor.secret_of(u) == "JBSWY3DPEHPK3PXP"


def test_tokens_carry_the_session_id() -> None:
    uid, tid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    access = verify_token(create_access_token(uid, tid, "admin", sid=sid))
    refresh = verify_token(create_refresh_token(uid, sid=sid))
    assert access["sid"] == str(sid) and refresh["sid"] == str(sid)
    assert "sid" not in verify_token(create_access_token(uid, tid, "admin"))


def test_purpose_token_expires() -> None:
    uid = uuid.uuid4()
    tok = create_purpose_token(uid, "password_reset", 5, pwf="abc")
    p = verify_token(tok)
    assert p["type"] == "password_reset" and p["pwf"] == "abc"
    assert p["exp"] - int(time.time()) <= 300
    assert verify_token(create_purpose_token(uid, "password_reset", -1)) == {}


def test_reset_link_dies_once_the_password_changes() -> None:
    from app.routers.auth import password_fingerprint, reset_email

    u = types.SimpleNamespace(password_hash="$2b$12$first")
    before = password_fingerprint(u)
    u.password_hash = "$2b$12$second"
    assert password_fingerprint(u) != before
    text, html = reset_email("Ann", "http://localhost:3100/auth/reset?token=t")
    assert "http://localhost:3100/auth/reset?token=t" in text
    assert "30 minutes" in text and 'href="http://localhost:3100' in html


def test_password_rules() -> None:
    from app.routers.settings import password_problem

    assert password_problem("short")
    assert password_problem("x" * 129)
    assert password_problem("long enough") is None


def test_verify_password_tolerates_sso_accounts() -> None:
    assert verify_password("anything", None) is False
    assert verify_password("", "$2b$12$abc") is False
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_session_tokens_helper() -> None:
    from app.core import sessions

    u = types.SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=types.SimpleNamespace(value="user"),
    )
    row = types.SimpleNamespace(id=uuid.uuid4())
    pair = sessions.tokens(u, row)
    assert verify_token(pair["access_token"])["sid"] == str(row.id)
    assert verify_token(pair["refresh_token"])["type"] == "refresh"


def test_client_ip_prefers_forwarded_for() -> None:
    from app.core.sessions import client_ip

    req = types.SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        client=types.SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.9"
    req.headers = {}
    assert client_ip(req) == "127.0.0.1"
    assert client_ip(None) is None


@pytest.mark.parametrize(
    "value,port,want",
    [
        ("auto", 587, None),
        ("false", 1025, False),
        ("true", 587, True),
        ("auto", 465, False),
    ],
)
def test_mailer_starttls_setting(monkeypatch, value, port, want) -> None:
    from app.core import mailer

    monkeypatch.setenv("SMTP_STARTTLS", value)
    assert mailer._start_tls(port) is want


def test_mailer_frontend_links(monkeypatch) -> None:
    from app.core import mailer

    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3100/")
    assert mailer.frontend_url("/approvals") == "http://localhost:3100/approvals"
    assert mailer.frontend_url("settings") == "http://localhost:3100/settings"
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert mailer.available() is False
