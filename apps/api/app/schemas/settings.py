from __future__ import annotations

from pydantic import BaseModel, EmailStr


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    avatar_url: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateApiKeyRequest(BaseModel):
    name: str


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "user"


class UpdateMemberRoleRequest(BaseModel):
    role: str


class NotificationSettingsRequest(BaseModel):
    execution_complete: bool = True
    execution_failed: bool = True
    weekly_report: bool = False
    billing_alerts: bool = True
    team_updates: bool = True
    marketing: bool = False
