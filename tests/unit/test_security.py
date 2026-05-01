"""Tests for app.core.security — bcrypt + RS256 JWT primitives.

These are the load-bearing auth primitives. A regression in either
hashing or token signing/verification is a security incident, so the
tests aim to exercise both happy paths and adversarial cases (wrong
password, tampered token, expired token).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)

# ── bcrypt password hashing ─────────────────────────────────────────


def test_hash_password_produces_bcrypt_hash():
    h = hash_password("hunter2")
    # bcrypt hashes start with a versioned prefix (e.g. $2b$, $2a$, $2y$)
    assert h.startswith(("$2a$", "$2b$", "$2y$"))
    # Cost factor is encoded into the hash; 60-character output total.
    assert len(h) == 60


def test_verify_password_round_trip():
    plaintext = "correct-horse-battery-staple"
    h = hash_password(plaintext)
    assert verify_password(plaintext, h) is True


def test_verify_password_rejects_wrong_password():
    h = hash_password("Right-Password!1")
    assert verify_password("wrong-password", h) is False
    # Case-sensitivity is preserved.
    assert verify_password("right-password!1", h) is False


def test_hash_password_uses_unique_salt():
    """Two calls with the same plaintext must yield different hashes."""
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    # …but both must verify.
    assert verify_password("same", a)
    assert verify_password("same", b)


# ── JWT access + refresh tokens ─────────────────────────────────────


def test_create_access_token_round_trip():
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id, tenant_id, "admin")
    claims = verify_token(token)

    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["role"] == "admin"
    assert claims["type"] == "access"
    assert "exp" in claims
    assert "iat" in claims


def test_create_refresh_token_has_no_tenant_or_role():
    """Refresh tokens are deliberately narrower — they only carry the
    user id and a 'refresh' type so a stolen refresh token can't be
    replayed as an access token."""
    user_id = uuid.uuid4()
    token = create_refresh_token(user_id)
    claims = verify_token(token)

    assert claims["sub"] == str(user_id)
    assert claims["type"] == "refresh"
    # Access-only fields must NOT be in a refresh payload
    assert "tenant_id" not in claims
    assert "role" not in claims


def test_verify_token_returns_empty_dict_on_garbage():
    assert verify_token("not-a-jwt") == {}
    assert verify_token("a.b.c") == {}
    assert verify_token("") == {}


def test_verify_token_rejects_tampered_payload():
    """If a caller flips a byte in the JWT, signature verification must
    fail and verify_token must return an empty dict (rather than raise)."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id, tenant_id, "user")
    # Flip a character in the middle (payload section).
    pos = len(token) // 2
    tampered = token[:pos] + ("X" if token[pos] != "X" else "Y") + token[pos + 1 :]
    assert verify_token(tampered) == {}


def test_verify_token_rejects_expired_token():
    """Hand-construct a JWT with an expiry in the past using the same
    private key, and verify that verification refuses it."""
    from app.core.security import _get_keys

    private_key, _ = _get_keys()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": "user",
        "type": "access",
        "exp": now - timedelta(minutes=5),
        "iat": now - timedelta(minutes=10),
    }
    expired = jwt.encode(payload, private_key, algorithm="RS256")
    assert verify_token(expired) == {}


def test_access_and_refresh_tokens_are_distinct_for_same_user():
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    a = create_access_token(user_id, tenant_id, "admin")
    # Tiny delay so iat differs even at second precision.
    time.sleep(0.01)
    r = create_refresh_token(user_id)
    assert a != r
    assert verify_token(a)["type"] == "access"
    assert verify_token(r)["type"] == "refresh"


def test_access_token_rejects_signing_with_wrong_key():
    """A token signed with a different key must NOT verify against the
    real public key. Guards against accidental key-mismatch in CI."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": "admin",
            "type": "access",
            "exp": now + timedelta(minutes=15),
            "iat": now,
        },
        rogue_pem,
        algorithm="RS256",
    )
    assert verify_token(forged) == {}


@pytest.mark.parametrize("role", ["admin", "user", "viewer", ""])
def test_role_round_trips_intact(role):
    """Role must arrive at /api/auth/me byte-identical to what was minted —
    RBAC checks compare it case-sensitively."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(user_id, tenant_id, role)
    assert verify_token(token)["role"] == role
