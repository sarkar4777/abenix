from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateTriggerRequest(BaseModel):
    agent_id: str
    trigger_type: str = Field(pattern="^(webhook|schedule)$")
    name: str | None = None
    cron_expression: str | None = None
    default_message: str = "Triggered execution"
    default_context: dict[str, Any] | None = None


class UpdateTriggerRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    cron_expression: str | None = None
    default_message: str | None = None
    default_context: dict[str, Any] | None = None
