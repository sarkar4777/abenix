"""A JWT key pair kept on one line in .env, newlines as \n, signs and verifies."""

from __future__ import annotations

import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import security


def _pem_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv, pub


def test_one_line_keys_sign_and_verify(monkeypatch):
    priv, pub = _pem_pair()
    monkeypatch.setattr(security.settings, "jwt_private_key", priv.replace("\n", "\n"))
    monkeypatch.setattr(security.settings, "jwt_public_key", pub.replace("\n", "\n"))
    monkeypatch.setattr(security, "_private_key", None)
    monkeypatch.setattr(security, "_public_key", None)
    token = security.create_access_token(uuid.uuid4(), uuid.uuid4(), "admin")
    claims = security.verify_token(token)
    assert claims["role"] == "admin"
