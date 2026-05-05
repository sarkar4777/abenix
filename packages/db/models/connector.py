"""Connector model — tenant-scoped external system connectors (CMMS, HRIS, telematics, etc.)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class ConnectorKind(str, enum.Enum):
    cmms = "cmms"
    hris = "hris"
    telematics = "telematics"
    standards = "standards"
    weather = "weather"
    cost_data = "cost_data"
    custom = "custom"


class ConnectorAuthType(str, enum.Enum):
    none = "none"
    api_key = "api_key"
    bearer = "bearer"
    basic = "basic"
    oauth2 = "oauth2"


class Connector(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "connectors"

    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[ConnectorKind] = mapped_column(
        Enum(ConnectorKind, name="connector_kind"), index=True
    )
    preset_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    auth_type: Mapped[ConnectorAuthType] = mapped_column(
        Enum(ConnectorAuthType, name="connector_auth_type"),
        default=ConnectorAuthType.none,
    )
    secret_ref: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
