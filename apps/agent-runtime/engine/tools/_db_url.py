"""DATABASE_URL helpers shared by tools that talk to Postgres directly.

The k8s helm values + dev-local.sh both provide DATABASE_URL in the
asyncpg form: `postgresql+asyncpg://user:pass@host:port/db?ssl=disable`.

Memory tools, drift detection, and other tool-side persistence layers
need an async URL. This helper:
  1. Falls back to env when the caller didn't pass `db_url=` explicitly.
  2. Coerces a sync `postgresql://` to the async `postgresql+asyncpg://`
     form so the same URL works everywhere.
  3. Strips asyncpg-incompatible `?ssl=disable` query params (asyncpg
     uses kwargs, not URL params; passing it via the URL raises).
"""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def resolve_async_db_url(passed_in: str | None = None) -> str:
    """Return a usable async-driver DATABASE_URL or empty string."""
    candidate = (passed_in or "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not candidate:
        return ""
    return _normalise(candidate)


def resolve_sync_db_url(passed_in: str | None = None) -> str:
    """Return a usable sync-driver DATABASE_URL or empty string.

    Used by the few tools that genuinely need psycopg2 (e.g. anything
    invoking sqlalchemy.create_engine without an async runtime).
    """
    candidate = (passed_in or "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not candidate:
        return ""
    candidate = _strip_problem_params(candidate)
    if candidate.startswith("postgresql+asyncpg://"):
        candidate = "postgresql+psycopg2://" + candidate[len("postgresql+asyncpg://") :]
    elif candidate.startswith("postgres://"):
        candidate = "postgresql+psycopg2://" + candidate[len("postgres://") :]
    elif (
        candidate.startswith("postgresql://")
        and "+" not in candidate.split("://", 1)[0]
    ):
        candidate = "postgresql+psycopg2://" + candidate[len("postgresql://") :]
    return candidate


def _normalise(url: str) -> str:
    url = _strip_problem_params(url)
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def _strip_problem_params(url: str) -> str:
    """Drop URL params that asyncpg rejects (it wants connect kwargs)."""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    qs = parse_qs(parts.query, keep_blank_values=True)
    # asyncpg doesn't accept ?ssl=disable as a URL param. The connection
    # is non-TLS by default in the dev cluster anyway.
    qs.pop("ssl", None)
    qs.pop("sslmode", None)
    new_query = urlencode({k: v[0] for k, v in qs.items()})
    return urlunparse(parts._replace(query=new_query))
