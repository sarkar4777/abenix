"""RFC 6238 time-based one-time codes, the kind authenticator apps show."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    n = struct.unpack(">I", digest[off : off + 4])[0] & 0x7FFFFFFF
    return str(n % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def verify(
    secret: str, code: str, *, last_step: int | None = None, now: float | None = None
) -> int | None:
    """The matched step, or None. One step of clock drift either way is allowed."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    here = current_step(now)
    for step in (here, here - 1, here + 1):
        # a code already used cannot sign in again
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "Abenix") -> str:
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP}"
    )


def new_recovery_codes(n: int = 8) -> list[str]:
    out = []
    for _ in range(n):
        raw = secrets.token_hex(5)
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def digest_code(code: str) -> str:
    norm = "".join(ch for ch in str(code or "").lower() if ch.isalnum())
    return hashlib.sha256(norm.encode()).hexdigest()
