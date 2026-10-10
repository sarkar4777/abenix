import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

_private_key: str | None = None
_public_key: str | None = None


def _get_keys() -> tuple[str, str]:
    global _private_key, _public_key
    if _private_key and _public_key:
        return _private_key, _public_key

    if settings.jwt_private_key and settings.jwt_public_key:
        # a key kept on one line in .env has its line breaks written as \n
        _private_key = settings.jwt_private_key.replace("\\n", "\n").strip()
        _public_key = settings.jwt_public_key.replace("\\n", "\n").strip()
        return _private_key, _public_key

    if not settings.debug:
        raise RuntimeError(
            "JWT_PRIVATE_KEY and JWT_PUBLIC_KEY must be set in production mode"
        )

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    _public_key = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return _private_key, _public_key


def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    sid: uuid.UUID | str | None = None,
) -> str:
    private_key, _ = _get_keys()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "type": "access",
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": now,
    }
    if sid:
        payload["sid"] = str(sid)
    return jwt.encode(payload, private_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID, sid: uuid.UUID | str | None = None) -> str:
    private_key, _ = _get_keys()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
        "iat": now,
    }
    if sid:
        payload["sid"] = str(sid)
    return jwt.encode(payload, private_key, algorithm=settings.jwt_algorithm)


def create_purpose_token(
    user_id: uuid.UUID, purpose: str, minutes: int, **claims: str
) -> str:
    """Short single-purpose token, a reset link or a second sign-in step."""
    private_key, _ = _get_keys()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": purpose,
        "exp": now + timedelta(minutes=minutes),
        "iat": now,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict:
    _, public_key = _get_keys()
    try:
        return jwt.decode(token, public_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return {}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    # SSO-only accounts have no password to match
    if not hashed or not plain:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False
