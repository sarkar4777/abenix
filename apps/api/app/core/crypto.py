"""Per-tenant envelope encryption for at-rest sensitive fields.

Encrypts values with AES-256-GCM, wrapping the per-tenant DEK with a
cluster-wide KEK held in `ABENIX_DATA_KEY_KEK_BASE64` (32-byte base64,
generated once and stored in a secret manager — Azure Key Vault, AWS
KMS, Hashicorp Vault).

A tenant's DEK is derived from `hash(KEK, tenant_id)` so it's
deterministic across pods but cannot be reproduced without the KEK.
Operationally simple and good enough for SOC 2; a future revision can
swap to per-tenant DEK rows for rotation.

Usage from a SQLAlchemy model:

    value: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)

The TypeDecorator silently encrypts on write and decrypts on read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import uuid


logger = logging.getLogger(__name__)

KEY_VERSION = 1
_NONCE_SIZE = 12
_TAG_SIZE = 16


def _kek() -> bytes:
    raw = os.environ.get("ABENIX_DATA_KEY_KEK_BASE64", "").strip()
    if not raw:
        return b"\x00" * 32
    try:
        kek = base64.b64decode(raw)
        if len(kek) != 32:
            raise ValueError(f"KEK must be 32 bytes after b64-decode, got {len(kek)}")
        return kek
    except Exception:
        logger.exception("invalid ABENIX_DATA_KEY_KEK_BASE64; encryption disabled")
        return b"\x00" * 32


def _derive_dek(tenant_id: uuid.UUID | str) -> bytes:
    tenant_str = str(tenant_id).encode("utf-8")
    return hmac.new(_kek(), tenant_str, hashlib.sha256).digest()


def _is_kek_configured() -> bool:
    return _kek() != b"\x00" * 32


def encrypt(tenant_id: uuid.UUID | str, plaintext: str) -> str:
    """Returns 'v1:<b64(nonce || ciphertext || tag)>'."""
    if not _is_kek_configured():
        return plaintext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        logger.warning("cryptography not installed; storing plaintext")
        return plaintext
    nonce = secrets.token_bytes(_NONCE_SIZE)
    dek = _derive_dek(tenant_id)
    aesgcm = AESGCM(dek)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"v{KEY_VERSION}:" + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(tenant_id: uuid.UUID | str, ciphertext: str) -> str:
    if not ciphertext or not ciphertext.startswith("v"):
        return ciphertext
    try:
        version_str, blob = ciphertext.split(":", 1)
    except ValueError:
        return ciphertext
    if not _is_kek_configured():
        return ciphertext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return ciphertext
    try:
        raw = base64.b64decode(blob)
        nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        dek = _derive_dek(tenant_id)
        aesgcm = AESGCM(dek)
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        logger.exception("decrypt failed for v=%s", version_str)
        return ciphertext


# Convenience: tenant-context shim used by TypeDecorator. Tests set
# `current_tenant_id` directly.
class TenantContext:
    current_tenant_id: uuid.UUID | None = None


_ctx = TenantContext()


def set_tenant(tenant_id: uuid.UUID | None) -> None:
    _ctx.current_tenant_id = tenant_id


def get_tenant() -> uuid.UUID | None:
    return _ctx.current_tenant_id


__all__ = [
    "encrypt",
    "decrypt",
    "KEY_VERSION",
    "set_tenant",
    "get_tenant",
]
