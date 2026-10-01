"""How a tool credential is written to the database and read back.

Platform rows live in platform_settings, tenant rows in
tenant_tool_credentials. Both are encrypted with the cluster KEK
(`ABENIX_DATA_KEY_KEK_BASE64`) when one is configured, using the same AES-GCM
helper the data layer uses, under one fixed scope, so the runtime decodes
every row the same way whichever table it came from. Without a KEK the value
is stored as it is, which is how the subscription token has always been
stored, and the admin screen says so.

The runtime decodes through the same function, so a value saved here reads
back in the agent-runtime pod as long as both pods carry the KEK, which the
chart's secret already gives them.
"""

from __future__ import annotations

from app.core import crypto
from engine import credentials

PLATFORM_SCOPE = credentials.PLATFORM_SCOPE
TENANT_TABLE = credentials.TENANT_TABLE


def encrypted_at_rest() -> bool:
    return crypto._is_kek_configured()


def encode_for_storage(value: str) -> str:
    return crypto.encrypt(PLATFORM_SCOPE, value)


def decode_stored(value: str) -> str:
    return credentials.decode_stored(value)
