from __future__ import annotations

from pydantic import BaseModel, Field

VALID_EVENTS = {
    "execution.completed",
    "execution.failed",
    "execution.started",
    "agent.published",
    "agent.updated",
    "*",
}


class CreateWebhookRequest(BaseModel):
    url: str = Field(min_length=10, max_length=1000)
    events: list[str] = Field(
        default=["execution.completed", "execution.failed"],
        min_length=1,
    )


class UpdateWebhookRequest(BaseModel):
    url: str | None = Field(default=None, min_length=10, max_length=1000)
    events: list[str] | None = None
    is_active: bool | None = None
