from pydantic import BaseModel, Field

from app.core.config import settings


class CreateReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class SubscribeRequest(BaseModel):
    plan_type: str = "free"
    success_url: str = Field(default_factory=lambda: f"{settings.frontend_url}/marketplace?subscribed=true")
    cancel_url: str = Field(default_factory=lambda: f"{settings.frontend_url}/marketplace")
