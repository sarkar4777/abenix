"""What every knowledge connector provides, the sync engine does the rest.

A connector lists pages of remote items and fetches their bytes. The engine in
apps/worker/worker/tasks/kb_connector_sync.py keeps the cursor, compares versions,
ingests, retries and detects deletes, so a new source only writes these parts.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, ClassVar, TypeVar

T = TypeVar("T")


class ConnectorError(Exception):
    """Nothing a retry can fix, the message is shown to the person who set it up."""


class ConfigError(ConnectorError):
    pass


class AuthError(ConnectorError):
    pass


class TransientError(ConnectorError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TooLarge(ConnectorError):
    pass


class Gone(ConnectorError):
    """A saved position the source no longer honours, start over from scratch."""


@dataclass
class Field:
    name: str
    label: str
    kind: str = "text"  # text, secret, number, bool, textarea
    required: bool = False
    help: str = ""
    default: Any = None
    secret: bool = False


@dataclass
class RemoteItem:
    external_id: str
    name: str
    version: str | None
    size: int | None = None
    modified_at: datetime | None = None
    # public True, False or None when the source does not say, principals carry emails
    acl: dict[str, Any] | None = None
    content: bytes | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Page:
    items: list[RemoteItem] = field(default_factory=list)
    # ids known to still exist, without their content, for delete detection
    seen: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    next_cursor: dict[str, Any] | None = None
    finished: bool = False
    # what the next pass starts from once this one ends
    sync_cursor: dict[str, Any] | None = None


class Connector:
    kind: ClassVar[str] = ""
    label: ClassVar[str] = ""
    # a finished pass saw everything, so whatever it did not see is gone
    complete_listing: ClassVar[bool] = True
    # never called against the real service, shown plainly in the screen
    verified_live: ClassVar[bool] = False
    needs_admin: ClassVar[bool] = False
    fields: ClassVar[list[Field]] = []

    def __init__(
        self, config: dict[str, Any], secrets: dict[str, str], **options: Any
    ) -> None:
        self.config = config or {}
        self.secrets = secrets or {}
        self.options = options

    def cfg(self, name: str, default: Any = None) -> Any:
        value = self.config.get(name)
        return default if value in (None, "") else value

    def secret(self, name: str) -> str:
        return (self.secrets.get(name) or "").strip()

    @classmethod
    def check_fields(cls, config: dict[str, Any], secrets: dict[str, str]) -> None:
        for f in cls.fields:
            have = secrets.get(f.name) if f.secret else config.get(f.name)
            if f.required and have in (None, ""):
                raise ConfigError(f"{f.label} is required for {cls.label}.")

    async def validate(self) -> None:
        """Called at save and before every sync, so a rule change applies to old sources."""

    async def list_page(
        self, page_cursor: dict[str, Any] | None, sync_cursor: dict[str, Any] | None
    ) -> Page:
        raise NotImplementedError

    async def fetch(self, item: RemoteItem, max_bytes: int) -> bytes:
        if item.content is not None:
            return item.content
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    if retry_after is not None:
        return min(float(retry_after), 300.0)
    return min(60.0, 2.0**attempt) * (0.5 + random.random() / 2)


async def with_retries(
    call: Callable[[], Awaitable[T]],
    attempts: int = 4,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Transient failures back off, honouring Retry-After. Anything else goes straight up."""
    last: TransientError | None = None
    for attempt in range(attempts):
        try:
            return await call()
        except TransientError as e:
            last = e
            if attempt < attempts - 1:
                await sleep(backoff_delay(attempt, e.retry_after))
    assert last is not None
    raise last


def safe_filename(name: str, fallback: str = "item") -> str:
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return (base or fallback)[:400]
