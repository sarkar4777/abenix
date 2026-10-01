"""One-shot checks a tool runs against a credential from the admin screen.

Each returns ``(ok, message)``. The message is shown to the admin as is, so it
says what the provider answered rather than what the tool would have done.
"""

from __future__ import annotations

from typing import Any

import httpx

_TIMEOUT = 8.0


def _status_message(r: httpx.Response, accepted: str) -> tuple[bool, str]:
    if r.status_code in (401, 403):
        return False, f"HTTP {r.status_code}, the provider rejected the credential"
    if r.status_code == 429:
        return True, "HTTP 429, the credential is accepted but rate limited right now"
    if 200 <= r.status_code < 300:
        return True, accepted
    body = (r.text or "")[:160].replace("\n", " ")
    return False, f"HTTP {r.status_code}: {body}"


async def probe(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    auth: tuple[str, str] | None = None,
    accepted: str = "accepted",
) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(
                method, url, headers=headers, params=params, json=json, auth=auth
            )
    except httpx.TimeoutException:
        return False, "timed out reaching the provider"
    except httpx.HTTPError as exc:
        return False, f"could not reach the provider: {exc.__class__.__name__}"
    return _status_message(r, accepted)
