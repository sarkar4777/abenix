"""Acting Subject — RBAC delegation for third-party SDK consumers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)

SUBJECT_HEADER = "X-Abenix-Subject"


@dataclass
class ActingSubject:
    """Represents an end user that the API key holder is acting on behalf of."""
    subject_type: str          # e.g., "example_app", "external", "user"
    subject_id: str            # the third-party system's user ID
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


def can_delegate(api_key_scopes: dict | list | None) -> bool:
    """Check if an API key has permission to delegate to other subjects."""
    if not api_key_scopes:
        return False
    if isinstance(api_key_scopes, dict):
        return bool(api_key_scopes.get("can_delegate", False))
    if isinstance(api_key_scopes, list):
        return "can_delegate" in api_key_scopes
    return False
