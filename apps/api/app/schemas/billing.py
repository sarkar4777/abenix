from pydantic import BaseModel, Field

from app.core.config import settings


class CheckoutRequest(BaseModel):
    plan: str
    success_url: str = Field(
        default_factory=lambda: f"{settings.frontend_url}/settings/billing?success=true"
    )
    cancel_url: str = Field(
        default_factory=lambda: f"{settings.frontend_url}/settings/billing?cancelled=true"
    )


class PortalRequest(BaseModel):
    return_url: str = Field(
        default_factory=lambda: f"{settings.frontend_url}/settings/billing"
    )
