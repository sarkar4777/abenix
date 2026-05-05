"""Pydantic schemas for the connector framework."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class ConnectorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(
        ...,
        description="cmms | hris | telematics | standards | weather | cost_data | custom",
    )
    preset_key: str | None = Field(default=None, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=1000)
    auth_type: str = Field(
        default="none", description="none | api_key | bearer | basic | oauth2"
    )
    secret_ref: uuid.UUID | None = Field(
        default=None, description="API key UUID storing the auth secret"
    )
    config: dict[str, Any] | None = Field(default=None)
    is_active: bool = Field(default=True)


class ConnectorUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    auth_type: str | None = None
    secret_ref: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None
    preset_key: str | None = None


class ConnectorOut(BaseModel):
    id: str
    name: str
    kind: str
    preset_key: str | None
    base_url: str
    auth_type: str
    secret_ref: str | None
    config: dict[str, Any] | None
    is_active: bool
    last_test_at: str | None
    last_test_ok: bool | None
    created_at: str | None
    updated_at: str | None
    operations: list[str] = []


class ConnectorTestResult(BaseModel):
    ok: bool
    latency_ms: int
    status_code: int | None = None
    sample_response_excerpt: str | None = None
    error: str | None = None


class ApprovalCreate(BaseModel):
    title: str = Field(default="Approval requested", max_length=255)
    payload: dict[str, Any] | None = None
    required_signoffs: int = Field(default=1, ge=1, le=10)
    expires_seconds: int | None = Field(default=86400, ge=10, le=604800)
    agent_id: uuid.UUID | None = None
    agent_execution_id: uuid.UUID | None = None


class ApprovalSignoffRequest(BaseModel):
    decision: str = Field(..., description="approve | deny")
    reason: str | None = Field(default=None, max_length=1000)
