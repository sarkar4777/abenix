"""The only way this app talks to Abenix: the vendored SDK.

Every call goes through the SDK, as in the other standalone apps. The one
endpoint the SDK has no typed method for, a run's event stream, is read
through ``sdk.http``, the SDK's authenticated client for exactly that case.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

import httpx

from abenix_sdk import Abenix, ActingSubject

from app.core.config import settings

logger = logging.getLogger("quoteiq.abenix")

_tasks: set[asyncio.Task[Any]] = set()


def new_sdk(timeout: float = 30.0) -> Abenix:
    return Abenix(base_url=settings.abenix_url, api_key=settings.api_key, timeout=timeout)


def acting_subject() -> ActingSubject:
    """The configured staff user, recorded by Abenix on every run."""
    return ActingSubject(
        subject_type="quoteiq",
        subject_id=settings.staff_id,
        display_name=settings.staff_name,
    )


def reviewed_by(note: str | None = None) -> str:
    """An approval's reason. Abenix records the API key's account as the signer,
    so the reviewer's name goes into the reason."""
    note = (note or "").strip()
    return f"Reviewed by {settings.staff_name}" + (f": {note}" if note else "")


def strip_reviewed_by(reason: str | None) -> str:
    """The note in a reason, without a leading "Reviewed by <name>:"."""
    text = (reason or "").strip()
    if text.startswith("Reviewed by "):
        _, sep, rest = text.partition(":")
        return rest.strip() if sep else ""
    return text


def describe(exc: BaseException) -> str:
    """A readable error, with Abenix's own message when it sent one.

    httpx timeouts stringify to "", which would leave an email showing a blank
    error with nothing to act on.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        message = ""
        try:
            body = exc.response.json()
            err = body.get("error") if isinstance(body, dict) else None
            message = (err.get("message") if isinstance(err, dict) else err) or body.get("detail") or ""
        except Exception:  # noqa: BLE001
            message = exc.response.text[:300]
        return f"Abenix answered {exc.response.status_code}" + (f": {message}" if message else "")
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def transient(exc: BaseException) -> bool:
    """An error worth trying again: the network, a timeout, or Abenix busy or
    restarting. A refusal (a bad key, an unknown run) is not."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code in {408, 429}
    # A proxy's HTML error page in place of JSON reads as a ValueError.
    return isinstance(exc, (httpx.TransportError, ValueError))


def spawn(coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
    """Run work in the background, keeping a reference so it isn't collected."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("background task %s failed", name, exc_info=t.exception())

    task.add_done_callback(_done)
    return task


async def cancel_all() -> None:
    for task in list(_tasks):
        task.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
