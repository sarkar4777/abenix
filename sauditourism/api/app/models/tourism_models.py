"""Saudi Tourism Analytics Platform models.

Separate user system from Abenix. All tables prefixed with `st_`.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Index,
    Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class STUserRole(str, enum.Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class DatasetType(str, enum.Enum):
    VISITOR_ARRIVALS = "visitor_arrivals"
    HOTEL_OCCUPANCY = "hotel_occupancy"
    REVENUE = "revenue"
    SATISFACTION_SURVEY = "satisfaction_survey"
    STRATEGY_REPORT = "strategy_report"
    IMPACT_STUDY = "impact_study"
    GENERAL = "general"


class DatasetStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    ERROR = "error"


class Region(str, enum.Enum):
    RIYADH = "riyadh"
    MAKKAH = "makkah"
    MADINAH = "madinah"
    EASTERN = "eastern"
    JEDDAH = "jeddah"
    NEOM = "neom"
    ALULA = "alula"
    ASIR = "asir"
    TABUK = "tabuk"


class SimulationType(str, enum.Enum):
    VISA_POLICY = "visa_policy"
    HOTEL_CAPACITY = "hotel_capacity"
    SEASONAL_PLANNING = "seasonal_planning"
    WEATHER_IMPACT = "weather_impact"
    COMPETITOR_ANALYSIS = "competitor_analysis"


class STUser(UUIDMixin, Base):
    """Saudi Tourism users — separate from Abenix users."""
    __tablename__ = "st_users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[STUserRole] = mapped_column(
        Enum(STUserRole, name="st_user_role", values_callable=lambda e: [m.value for m in e]),
        default=STUserRole.ANALYST,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    datasets: Mapped[list["STDataset"]] = relationship(back_populates="user")


class STDataset(UUIDMixin, Base):
    """An uploaded tourism dataset (CSV or PDF)."""
    __tablename__ = "st_datasets"
    __table_args__ = (
        Index("ix_st_datasets_user", "user_id"),
        Index("ix_st_datasets_type", "dataset_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("st_users.id"))
    dataset_type: Mapped[DatasetType] = mapped_column(
        Enum(DatasetType, name="dataset_type", values_callable=lambda e: [m.value for m in e])
    )
    title: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[DatasetStatus] = mapped_column(
        Enum(DatasetStatus, name="dataset_status", values_callable=lambda e: [m.value for m in e]),
        default=DatasetStatus.UPLOADED,
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    columns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["STUser"] = relationship(back_populates="datasets")
    # analytics_results are cached by user, not per-dataset


class STAnalyticsResult(UUIDMixin, Base):
    """Computed analytics — cached agent results."""
    __tablename__ = "st_analytics_results"

    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("st_users.id"))
    analysis_type: Mapped[str] = mapped_column(String(100))
    results: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # No FK relationship — dataset_id is optional for cached analytics


class STSimulation(UUIDMixin, Base):
    """Simulation runs and results."""
    __tablename__ = "st_simulations"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("st_users.id"))
    simulation_type: Mapped[SimulationType] = mapped_column(
        Enum(SimulationType, name="simulation_type", values_callable=lambda e: [m.value for m in e])
    )
    title: Mapped[str] = mapped_column(String(500))
    parameters: Mapped[dict] = mapped_column(JSONB)
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class STChatMessage(UUIDMixin, Base):
    """Chat history for tourism Q&A."""
    __tablename__ = "st_chat_messages"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("st_users.id"))
    role: Mapped[str] = mapped_column(String(20))  # user, assistant
    content: Mapped[str] = mapped_column(Text)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class STReport(UUIDMixin, Base):
    """Generated executive reports."""
    __tablename__ = "st_reports"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("st_users.id"))
    title: Mapped[str] = mapped_column(String(500))
    report_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
