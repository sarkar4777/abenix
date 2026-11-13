"""QuoteIQ settings, read from the environment once at import."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    abenix_url: str
    abenix_web_url: str
    api_key: str
    # The app has no sign-in. It acts as this one staff user, as if a sign-in
    # had supplied the name: the acting user on every run, the person who
    # signs the emails and the reviewer named on every approval.
    staff_name: str
    pipeline_slug: str
    drafter_slug: str
    run_timeout_seconds: int
    redraft_timeout_seconds: int
    approval_poll_seconds: int
    # The longest expiry Abenix allows an approval raised through the API.
    review_expiry_seconds: int = 7 * 24 * 3600

    @property
    def staff_id(self) -> str:
        return re.sub(r"[^a-z0-9]+", ".", self.staff_name.lower()).strip(".") or "staff"

    def run_url(self, execution_id: str | None) -> str | None:
        if not execution_id:
            return None
        return f"{self.abenix_web_url.rstrip('/')}/executions/{execution_id}"


def load_settings() -> Settings:
    return Settings(
        abenix_url=os.environ.get("ABENIX_API_URL", "http://localhost:8000"),
        abenix_web_url=os.environ.get("ABENIX_WEB_URL", "http://localhost:3000"),
        api_key=os.environ.get("QUOTEIQ_ABENIX_API_KEY", ""),
        staff_name=os.environ.get("QQ_STAFF_NAME", "").strip() or "Priya Shah",
        pipeline_slug=os.environ.get("QQ_PIPELINE_SLUG", "quoteiq-rfq"),
        drafter_slug=os.environ.get("QQ_DRAFTER_SLUG", "quoteiq-email-drafter"),
        run_timeout_seconds=_int("QQ_RUN_TIMEOUT_SECONDS", 600),
        redraft_timeout_seconds=_int("QQ_REDRAFT_TIMEOUT_SECONDS", 180),
        approval_poll_seconds=_int("QQ_APPROVAL_POLL_SECONDS", 10),
    )


settings = load_settings()
