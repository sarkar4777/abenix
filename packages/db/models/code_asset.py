"""Code Asset — a user-uploaded repo or zip that becomes a callable"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Index,
    Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class CodeAssetSource(str, enum.Enum):
    ZIP = "zip"
    GIT = "git"


class CodeAssetStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class CodeAsset(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "code_assets"
    __table_args__ = (
        Index("ix_code_assets_tenant_name", "tenant_id", "name"),
        Index("ix_code_assets_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_type: Mapped[CodeAssetSource] = mapped_column(
        Enum(CodeAssetSource, name="code_asset_source",
             values_callable=lambda e: [m.value for m in e]),
    )
    # One of the two is set:
    source_git_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # branch/tag/commit for git assets

    # Storage URI to the materialized zip (S3 or local path)
    storage_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Analysis results (populated by analyzer)
    detected_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    detected_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    detected_package_manager: Mapped[str | None] = mapped_column(String(50), nullable=True)
    detected_entrypoint: Mapped[str | None] = mapped_column(String(500), nullable=True)

    suggested_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_build_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_run_command: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free-form analyzer notes: gaps, warnings, missing deps, LLM suggestions
    analysis_notes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # shape: [{"level": "warn|info|error", "message": "...", "suggestion": "..."}, ...]

    # User-declared I/O contract. If unset, the executor uses a
    # pass-through (raw stdin → stdout) which is fine for smoke tests
    # but doesn't let AI Builder reason about types.
    input_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # e.g. {"type":"object","properties":{"city":{"type":"string"}}, "required":["city"]}
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # e.g. {"type":"object","properties":{"weather":{"type":"string"}}}

    # Status flow
    status: Mapped[CodeAssetStatus] = mapped_column(
        Enum(CodeAssetStatus, name="code_asset_status",
             values_callable=lambda e: [m.value for m in e]),
        default=CodeAssetStatus.UPLOADED,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Last successful test run's output (for UI display)
    last_test_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_test_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
