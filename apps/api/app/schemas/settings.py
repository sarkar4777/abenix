from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    avatar_url: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: dict | None = None
    expires_at: datetime | None = None
    max_monthly_tokens: int | None = None
    max_monthly_cost: float | None = None
    # Cross-tenant mint reserved for platform superadmin; silently ignored otherwise.
    tenant_id: str | None = None


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "user"


class UpdateMemberRoleRequest(BaseModel):
    role: str


class NotificationChannels(BaseModel):
    slack: bool | None = None
    email: bool | None = None


class NotificationSettingsRequest(BaseModel):
    # Partial update, keys left out keep their saved value
    execution_complete: bool | None = None
    execution_failed: bool | None = None
    billing_alerts: bool | None = None
    team_updates: bool | None = None
    channels: NotificationChannels | None = None
