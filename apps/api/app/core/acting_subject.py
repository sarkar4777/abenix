"""Acting Subject — RBAC delegation for third-party SDK consumers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

SUBJECT_HEADER = "X-Abenix-Subject"


@dataclass
class ActingSubject:
    """Represents an end user that the API key holder is acting on behalf of."""

    subject_type: str  # e.g., "contractiq", "external", "user"
    subject_id: str  # the third-party system's user ID
    email: str | None = None
    display_name: str | None = None
    metadata: dict | None = None  # optional extra context

    @classmethod
    def from_header(cls, header_value: str | None) -> "ActingSubject | None":
        if not header_value:
            return None
        try:
            data = json.loads(header_value)
            return cls(
                subject_type=str(data.get("subject_type", "external")),
                subject_id=str(data["subject_id"]),
                email=data.get("email"),
                display_name=data.get("display_name"),
                metadata=data.get("metadata"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Invalid X-Abenix-Subject header: %s", e)
            return None

    def to_header(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items() if v is not None})

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def subject_columns_for(user) -> tuple[str | None, str | None]:
    """Return (subject_id, subject_type) to stamp on an Execution row.

    Every Execution-row creation site in apps/api/app/routers/* should pass
    its FastAPI-resolved `user` here. Returns (None, None) when the user has
    no actAs delegation, so the call is safe even for non-delegated flows.

    Centralising the lookup means: any future change to how delegation is
    attached (header name, scope shape, JWT claim) takes effect everywhere
    at once. Without this helper, each call site has to remember to do
    getattr(user, "_acting_subject", None) and risks dropping the stamp
    silently — which is exactly the bug we just paid for fixing in 10 places.
    """
    subject = getattr(user, "_acting_subject", None)
    if not subject:
        return None, None
    sid = str(subject.subject_id) if getattr(subject, "subject_id", None) else None
    stype = (
        str(subject.subject_type) if getattr(subject, "subject_type", None) else None
    )
    return sid, stype


def can_delegate(api_key_scopes: dict | list | None) -> bool:
    """Check if an API key has permission to delegate to other subjects.

    Handles every shape the api_keys.scopes jsonb column ships with:
      1. {"can_delegate": true}                         — explicit boolean
      2. {"allowed_actions": ["can_delegate", ...]}     — production shape
                                                          stamped by the
                                                          seed_users.py
                                                          standalone-key path
      3. ["can_delegate", ...]                          — bare-list legacy shape
    """
    if not api_key_scopes:
        return False
    if isinstance(api_key_scopes, dict):
        if bool(api_key_scopes.get("can_delegate", False)):
            return True
        allowed = (
            api_key_scopes.get("allowed_actions") or api_key_scopes.get("scopes") or []
        )
        if isinstance(allowed, list) and "can_delegate" in allowed:
            return True
        return False
    if isinstance(api_key_scopes, list):
        return "can_delegate" in api_key_scopes
    return False
