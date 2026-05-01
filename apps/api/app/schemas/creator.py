from pydantic import BaseModel, Field

from app.core.config import settings


class OnboardCreatorRequest(BaseModel):
    refresh_url: str = Field(
        default_factory=lambda: f"{settings.frontend_url}/creator?refresh=true"
    )
    return_url: str = Field(
        default_factory=lambda: f"{settings.frontend_url}/creator?onboarded=true"
    )
