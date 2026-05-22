"""ContractIQ — PPA & Gas Contract Intelligence Platform models."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Index,
    Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class ContractIQUserRole(str, enum.Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class ContractType(str, enum.Enum):
    PPA = "ppa"
    GAS = "gas"
    TOLLING = "tolling"
    VPPA = "vppa"
    METALS = "metals"


class AssetClass(str, enum.Enum):
    """Cross-type taxonomy that drives which market-data tools an agent reaches for."""

    POWER = "power"
    NATGAS = "natgas"
    LNG = "lng"
    CRUDE = "crude"
    GOLD = "gold"
    SILVER = "silver"
    PLATINUM = "platinum"
    PALLADIUM = "palladium"
    DORE = "dore"
    CONCENTRATE = "concentrate"
    CARBON = "carbon"
    MIXED = "mixed"


class PricingPattern(str, enum.Enum):
    """Shape of the price formula — drives valuation + what-if + reconciliation."""

    FIXED = "fixed"
    INDEXED = "indexed"
    CURVE_REFERENCED = "curve_referenced"
    FORMULA = "formula"
    SWAP = "swap"
    OPTION = "option"
    LEASE = "lease"
    UNKNOWN = "unknown"


class ContractStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    ANALYZED = "analyzed"
    ERROR = "error"


class ClauseType(str, enum.Enum):
    TERMINATION = "termination"
    FORCE_MAJEURE = "force_majeure"
    PRICING = "pricing"
    PAYMENT = "payment"
    PERFORMANCE_GUARANTEE = "performance_guarantee"
    CURTAILMENT = "curtailment"
    CHANGE_OF_LAW = "change_of_law"
    INSURANCE = "insurance"
    INDEMNITY = "indemnity"
    DISPUTE_RESOLUTION = "dispute_resolution"
    ASSIGNMENT = "assignment"
    CONFIDENTIALITY = "confidentiality"
    OTHER = "other"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContractIQUser(UUIDMixin, Base):
    """ContractIQ users — separate from Abenix users."""
    __tablename__ = "contractiq_users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[ContractIQUserRole] = mapped_column(
        Enum(ContractIQUserRole, name="contractiq_user_role", values_callable=lambda e: [m.value for m in e]),
        default=ContractIQUserRole.ANALYST,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contracts: Mapped[list["ContractIQContract"]] = relationship(back_populates="user")


class ContractIQContract(UUIDMixin, Base):
    """An uploaded PPA or Gas contract."""
    __tablename__ = "contractiq_contracts"
    __table_args__ = (
        Index("ix_contractiq_contracts_user", "user_id"),
        Index("ix_contractiq_contracts_type", "contract_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_type: Mapped[ContractType] = mapped_column(Enum(ContractType, name="contract_type", values_callable=lambda e: [m.value for m in e]))
    title: Mapped[str] = mapped_column(String(500))
    counterparty_a: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty_b: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contract_status", values_callable=lambda e: [m.value for m in e]), default=ContractStatus.UPLOADED,
    )
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    functional_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_capacity_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_value: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pricing_pattern: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[ContractIQUser] = relationship(back_populates="contracts")
    extracted_data: Mapped[list["ContractIQExtractedData"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    clauses: Mapped[list["ContractIQClause"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    assets: Mapped[list["ContractIQAsset"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    events: Mapped[list["ContractIQEvent"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    risk_analyses: Mapped[list["ContractIQRiskAnalysis"]] = relationship(back_populates="contract", cascade="all, delete-orphan")


class ContractIQExtractedData(UUIDMixin, Base):
    """Individual extracted fields from a contract."""
    __tablename__ = "contractiq_extracted_data"
    __table_args__ = (
        Index("ix_contractiq_extracted_contract", "contract_id", "section"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(String(100))  # commercial_terms, technical, legal, financial, assets
    field_name: Mapped[str] = mapped_column(String(255))
    field_value: Mapped[str] = mapped_column(Text)
    field_type: Mapped[str] = mapped_column(String(50), default="string")  # string, number, date, currency, percentage
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extraction_pass: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped[ContractIQContract] = relationship(back_populates="extracted_data")


class ContractIQClause(UUIDMixin, Base):
    """Contract clauses with risk classification."""
    __tablename__ = "contractiq_clauses"
    __table_args__ = (
        Index("ix_contractiq_clauses_contract", "contract_id"),
        Index("ix_contractiq_clauses_type", "clause_type"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    clause_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    clause_title: Mapped[str] = mapped_column(String(500))
    clause_text: Mapped[str] = mapped_column(Text)
    clause_type: Mapped[ClauseType] = mapped_column(Enum(ClauseType, name="clause_type", values_callable=lambda e: [m.value for m in e]), default=ClauseType.OTHER)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel, name="risk_level", values_callable=lambda e: [m.value for m in e]), default=RiskLevel.LOW)
    risk_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_dates: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    key_amounts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped[ContractIQContract] = relationship(back_populates="clauses")


class ContractIQAsset(UUIDMixin, Base):
    """Physical assets referenced in the contract."""
    __tablename__ = "contractiq_assets"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    asset_name: Mapped[str] = mapped_column(String(500))
    asset_type: Mapped[str] = mapped_column(String(100))  # solar_plant, wind_farm, gas_pipeline, storage, substation
    capacity_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    coordinates: Mapped[str | None] = mapped_column(String(100), nullable=True)  # lat,lng
    cod_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    technology: Mapped[str | None] = mapped_column(String(255), nullable=True)
    degradation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    interconnection_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metering_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped[ContractIQContract] = relationship(back_populates="assets")


class ContractIQEvent(UUIDMixin, Base):
    """Key dates, milestones, and events from the contract."""
    __tablename__ = "contractiq_events"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(100))  # milestone, deadline, review, renewal, termination_trigger
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_days_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="upcoming")  # upcoming, passed, triggered
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped[ContractIQContract] = relationship(back_populates="events")


class ContractIQRiskAnalysis(UUIDMixin, Base):
    """Risk assessment results."""
    __tablename__ = "contractiq_risk_analyses"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    analysis_type: Mapped[str] = mapped_column(String(50))  # single, comparison, portfolio
    risk_category: Mapped[str] = mapped_column(String(100))  # market, credit, operational, regulatory, legal, technology
    risk_score: Mapped[float] = mapped_column(Float, default=0)
    risk_description: Mapped[str] = mapped_column(Text)
    mitigation_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_data_used: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped[ContractIQContract] = relationship(back_populates="risk_analyses")


class ContractIQComparison(UUIDMixin, Base):
    """Saved contract comparisons."""
    __tablename__ = "contractiq_comparisons"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_ids: Mapped[list] = mapped_column(JSONB)  # Array of contract UUIDs
    comparison_type: Mapped[str] = mapped_column(String(50))  # side_by_side, risk_matrix, financial
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMarketAlert(UUIDMixin, Base):
    """Market-driven alerts when contract terms diverge from current market conditions."""
    __tablename__ = "contractiq_market_alerts"
    __table_args__ = (
        Index("ix_contractiq_alerts_contract", "contract_id"),
        Index("ix_contractiq_alerts_severity", "severity"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    alert_type: Mapped[str] = mapped_column(String(100))  # price_breach, fx_risk, carbon_risk, escalation_risk, market_favorable
    severity: Mapped[str] = mapped_column(String(20))  # info, warning, critical
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    market_data_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    contract_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    market_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped[ContractIQContract] = relationship()



class InsightStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─── 1. Daily Executive Briefing ────────────────────────────────────────
class ContractIQBriefing(UUIDMixin, Base):
    """Daily executive briefing — generated each morning summarising overnight changes."""
    __tablename__ = "contractiq_briefings"
    __table_args__ = (
        Index("ix_contractiq_briefings_user_date", "user_id", "for_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    for_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_actions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 2. Renewal Negotiation Copilot ─────────────────────────────────────
class ContractIQRenewalPacket(UUIDMixin, Base):
    """Negotiation packet generated for an upcoming contract renewal."""
    __tablename__ = "contractiq_renewal_packets"
    __table_args__ = (
        Index("ix_contractiq_renewal_user", "user_id"),
        Index("ix_contractiq_renewal_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    days_to_expiry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    historical_pricing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    counterparty_intel: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    term_sheet: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {aggressive, middle, fallback}
    npv_uplift: Mapped[float | None] = mapped_column(Float, nullable=True)
    full_packet_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 3. Force Majeure Response ──────────────────────────────────────────
class ContractIQFMNotice(UUIDMixin, Base):
    """Auto-drafted Force Majeure notice triggered by market or grid event."""
    __tablename__ = "contractiq_fm_notices"
    __table_args__ = (
        Index("ix_contractiq_fm_user", "user_id"),
        Index("ix_contractiq_fm_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    trigger_type: Mapped[str] = mapped_column(String(100))  # curtailment, pipeline_outage, fx_shock, regulation, weather
    trigger_description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    applicable_clauses: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    financial_impact_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    draft_notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline_to_notify: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft, awaiting_review, sent, dismissed
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 4. Settlement Reconciliation ───────────────────────────────────────
class ContractIQReconciliation(UUIDMixin, Base):
    """Invoice vs contract reconciliation result."""
    __tablename__ = "contractiq_reconciliations"
    __table_args__ = (
        Index("ix_contractiq_recon_user", "user_id"),
        Index("ix_contractiq_recon_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="SET NULL"), nullable=True)
    invoice_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invoice_period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_amount: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    expected_amount: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    variance_amount: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    variance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    line_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    discrepancies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dispute_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=InsightStatus.PENDING.value)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 5. Multi-Doc Contract Families ─────────────────────────────────────
class ContractIQContractFamily(UUIDMixin, Base):
    """A group of related contracts (master + amendments + side letters)."""
    __tablename__ = "contractiq_contract_families"
    __table_args__ = (
        Index("ix_contractiq_family_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    family_name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    master_contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="SET NULL"), nullable=True)
    member_contract_ids: Mapped[list] = mapped_column(JSONB, default=list)
    effective_clauses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # cached resolved clauses
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─── 6. Clause Anomaly Detection ────────────────────────────────────────
class ContractIQClauseAnomaly(UUIDMixin, Base):
    """Statistical outlier flag for an extracted clause."""
    __tablename__ = "contractiq_clause_anomalies"
    __table_args__ = (
        Index("ix_contractiq_anomaly_user", "user_id"),
        Index("ix_contractiq_anomaly_clause", "clause_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_clauses.id", ondelete="CASCADE"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    anomaly_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1, higher = more unusual
    severity: Mapped[str] = mapped_column(String(20), default="info")  # info, warning, critical
    explanation: Mapped[str] = mapped_column(Text)
    benchmark_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 7. Version Diff ─────────────────────────────────────────────────────
class ContractIQVersionDiff(UUIDMixin, Base):
    """Semantic comparison between two contract versions."""
    __tablename__ = "contractiq_version_diffs"
    __table_args__ = (
        Index("ix_contractiq_diff_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    base_contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    new_contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    changes: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{clause_type, change_kind, impact, before, after, rationale}]
    overall_impact: Mapped[str | None] = mapped_column(String(20), nullable=True)  # favourable, neutral, adverse, mixed
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 8. Stress Test Simulator ───────────────────────────────────────────
class ContractIQStressTest(UUIDMixin, Base):
    """Monte Carlo stress test of a contract or portfolio under market scenarios."""
    __tablename__ = "contractiq_stress_tests"
    __table_args__ = (
        Index("ix_contractiq_stress_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="single")  # single | portfolio
    name: Mapped[str] = mapped_column(String(500))
    scenario_params: Mapped[dict] = mapped_column(JSONB, default=dict)  # shocks: power_pct, fx_pct, etc.
    iterations: Mapped[int] = mapped_column(Integer, default=1000)
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    base_npv: Mapped[float | None] = mapped_column(Float, nullable=True)
    p5_npv: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_npv: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_npv: Mapped[float | None] = mapped_column(Float, nullable=True)
    var_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_shortfall: Mapped[float | None] = mapped_column(Float, nullable=True)
    distribution: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # histogram bins
    worst_scenarios: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 9. Hedge Recommendations ───────────────────────────────────────────
class ContractIQHedgeRecommendation(UUIDMixin, Base):
    """Hedge structure recommendation for a contract's floating exposure."""
    __tablename__ = "contractiq_hedge_recommendations"
    __table_args__ = (
        Index("ix_contractiq_hedge_user", "user_id"),
        Index("ix_contractiq_hedge_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    exposure_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # power_price, fx, interest_rate, carbon
    notional_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tenor_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structures: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{name, cost, residual_risk, premium_pct, description}]
    recommended_structure: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── 10. Counterparty Credit Risk ──────────────────────────────────────
class ContractIQCreditRisk(UUIDMixin, Base):
    """Counterparty credit risk assessment — updated periodically."""
    __tablename__ = "contractiq_credit_risks"
    __table_args__ = (
        Index("ix_contractiq_credit_user", "user_id"),
        Index("ix_contractiq_credit_counterparty", "counterparty_name"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    counterparty_name: Mapped[str] = mapped_column(String(255))
    ticker: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Credit ratings (S&P/Moody's/Fitch) and agency outputs can be longer than
    # the classic "A+" — e.g. "Not Rated (private)". Give them real room.
    credit_rating: Mapped[str | None] = mapped_column(String(80), nullable=True)
    credit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    altman_z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score_zone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    probability_of_default_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(40), nullable=True)  # Low/Medium/High/Critical etc.
    key_ratios: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    financial_highlights: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    risk_factors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mitigating_factors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    credit_mitigation_recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    monitoring_triggers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQKycCheck(UUIDMixin, Base):
    """KYC Standard Check Report — mirrors the MET Group template."""
    __tablename__ = "contractiq_kyc_checks"
    __table_args__ = (
        Index("ix_contractiq_kyc_user", "user_id"),
        Index("ix_contractiq_kyc_counterparty", "counterparty_name"),
        Index("ix_contractiq_kyc_created", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))

    # ── Administrative header ──
    profit_centre: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activity_trigger: Mapped[str | None] = mapped_column(String(30), nullable=True)  # Pre-Check/Periodic/Ad-hoc
    type_of_business_relationship: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Core/Noncore
    start_date_of_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Counterparty identity ──
    counterparty_name: Mapped[str] = mapped_column(String(255))
    counterparty_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_business: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_form: Mapped[str | None] = mapped_column(String(100), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lei: Mapped[str | None] = mapped_column(String(30), nullable=True)
    incorporation_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # ── Jurisdiction ──
    country_iso2: Mapped[str | None] = mapped_column(String(3), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sanctions_applicable: Mapped[bool] = mapped_column(default=False)

    # ── Indicators + aggregate ──
    indicator_i_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_i_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_i_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    indicator_ii_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_ii_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_ii_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    indicator_iii_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    indicator_iii_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_iii_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregated_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    type_of_check: Mapped[str | None] = mapped_column(String(30), nullable=True)  # Simplified/Standard/Enhanced

    # ── Basic compliance ──
    basic_compliance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {verification_of_legal_existence: {outcome, comment, evidence_urls}}

    # ── Intermediate compliance checks (list of line items) ──
    intermediate_checks: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Shareholder structure + UBOs ──
    shareholder_structure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ubos: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    discovery_gaps: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Review & sign-off ──
    summary_of_compliance_risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_consulted: Mapped[bool] = mapped_column(default=False)
    legal_opinion_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_of_check: Mapped[str | None] = mapped_column(String(20), nullable=True)  # positive/negative
    top_recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_docs_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    local_kyc_expert_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ── Raw agent output for audit ──
    raw_agent_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Meta ──
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )



# Wave 1 — Portfolio Valuation, Forward Curves, Take-or-Pay Monitor

class ContractIQForecastCurve(UUIDMixin, Base):
    """Forward price curve generated by `contractiq-price-forecaster`."""
    __tablename__ = "contractiq_forecast_curves"
    __table_args__ = (
        Index("ix_ciq_forecast_user_market_date", "user_id", "market", "base_date"),
        Index("ix_ciq_forecast_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id", ondelete="CASCADE"))
    market: Mapped[str] = mapped_column(String(120))
    methodology: Mapped[str] = mapped_column(String(40), default="market+sentiment")
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tenor_months: Mapped[int] = mapped_column(Integer, default=24)
    curve: Mapped[list | None] = mapped_column(JSONB, nullable=True)          # [{tenor_months, date, price, confidence_low, confidence_high, ...}]
    fundamental_drivers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_adjustment_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_agent_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQValuation(UUIDMixin, Base):
    """Portfolio mark-to-market or Take-or-Pay snapshot."""
    __tablename__ = "contractiq_valuations"
    __table_args__ = (
        Index("ix_ciq_valuations_user_type_created", "user_id", "valuation_type", "created_at"),
        Index("ix_ciq_valuations_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id", ondelete="CASCADE"))
    valuation_type: Mapped[str] = mapped_column(String(30))   # mtm | top_monitor
    scope: Mapped[str] = mapped_column(String(20), default="portfolio")
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="SET NULL"), nullable=True)
    valuation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Denormalised headline numbers for cheap list-views
    portfolio_mtm: Mapped[float | None] = mapped_column(Float, nullable=True)
    portfolio_mtm_ccy: Mapped[str | None] = mapped_column(String(10), nullable=True)
    total_shortfall_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQClauseBenchmark(UUIDMixin, Base):
    """Per-clause benchmark produced by `contractiq-clause-benchmarker`."""
    __tablename__ = "contractiq_clause_benchmarks"
    __table_args__ = (
        Index("ix_ciq_benchmark_user", "user_id"),
        Index("ix_ciq_benchmark_clause", "clause_id"),
        Index("ix_ciq_benchmark_contract", "contract_id"),
        Index("ix_ciq_benchmark_created", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id", ondelete="CASCADE"))
    clause_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_clauses.id", ondelete="CASCADE"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    clause_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stance: Mapped[str | None] = mapped_column(String(30), nullable=True)
    deviation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_standard_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    peer_comparisons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    suggested_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_agent_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=InsightStatus.PENDING.value)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQExtractionTaxonomy(UUIDMixin, Base):
    """Self-learning extraction taxonomy."""
    __tablename__ = "contractiq_extraction_taxonomy"
    __table_args__ = (
        Index(
            "ix_ciq_taxonomy_user_type_key",
            "user_id", "taxonomy_type", "key",
            unique=True,
        ),
        Index("ix_ciq_taxonomy_user_usage", "user_id", "usage_count"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id", ondelete="CASCADE"))
    taxonomy_type: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Freeform metadata — example legs under a cluster, field type under a
    # field, sample values, etc. Never used as a primary key.
    taxonomy_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQDealTemplate(UUIDMixin, Base):
    """Endur / Allegro / Openlink JSON deal templates per ETRM category."""

    __tablename__ = "contractiq_deal_templates"
    __table_args__ = (
        Index("ix_ciq_deal_templates_user_category", "user_id", "category"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractiq_users.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(80))   # e.g. power_physical
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_json: Mapped[dict] = mapped_column(JSONB)  # the skeleton with ${placeholders}
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False)  # pre-seeded vs uploaded
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─── Precious metals ────────────────────────────────────────────────────


class ContractIQMetalsExtraction(UUIDMixin, Base):

    __tablename__ = "contractiq_metals_extractions"
    __table_args__ = (
        Index("ix_ciq_metals_extract_user", "user_id"),
        Index("ix_ciq_metals_extract_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    material: Mapped[str | None] = mapped_column(String(40), nullable=True)
    material_form: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fineness_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    fineness_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    bar_weight_oz: Mapped[float | None] = mapped_column(Float, nullable=True)
    bar_weight_tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    good_delivery_standard: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accepted_refiners: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    loco: Mapped[str | None] = mapped_column(String(40), nullable=True)
    loco_other: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    late_delivery_penalty: Mapped[str | None] = mapped_column(Text, nullable=True)
    pricing_reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pricing_formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    settlement_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assay_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assay_tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    umpire_clause_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    split_sample_protocol: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provisional_payment_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    vaulting_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    insurance_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    insurance_min_coverage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    treatment_charge_per_tonne_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    refining_charge_per_oz_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    payable_percent_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    payable_percent_ag: Mapped[float | None] = mapped_column(Float, nullable=True)
    payable_percent_pt: Mapped[float | None] = mapped_column(Float, nullable=True)
    payable_percent_pd: Mapped[float | None] = mapped_column(Float, nullable=True)
    impurity_penalties: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    compliance_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    russian_origin_excluded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ofac_clause_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMetalsCompliance(UUIDMixin, Base):

    __tablename__ = "contractiq_metals_compliance"
    __table_args__ = (
        Index("ix_ciq_metals_comp_user", "user_id"),
        Index("ix_ciq_metals_comp_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    block_level_issues: Mapped[int] = mapped_column(Integer, default=0)
    clarification_requests: Mapped[int] = mapped_column(Integer, default=0)
    verdicts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    superseded_references: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMetalsDisputeRisk(UUIDMixin, Base):

    __tablename__ = "contractiq_metals_dispute_risk"
    __table_args__ = (
        Index("ix_ciq_metals_dr_user", "user_id"),
        Index("ix_ciq_metals_dr_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    aggregate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_loss_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_loss_pct_of_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    dimensions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    top_recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    comparable_disputes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMetalsLoco(UUIDMixin, Base):

    __tablename__ = "contractiq_metals_loco"
    __table_args__ = (
        Index("ix_ciq_metals_loco_user", "user_id"),
        Index("ix_ciq_metals_loco_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    loco: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_price_usd_per_oz: Mapped[float | None] = mapped_column(Float, nullable=True)
    loco_premium_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    loco_premium_usd_per_oz: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparison: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    insurance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    customs_tariff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    chain_of_integrity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    repatriation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    vault_handover: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    alerts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMetalsSourcing(UUIDMixin, Base):

    __tablename__ = "contractiq_metals_sourcing"
    __table_args__ = (
        Index("ix_ciq_metals_sourcing_user", "user_id"),
        Index("ix_ciq_metals_sourcing_contract", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    origin_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    origin_risk_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mine_disclosed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mine_identity: Mapped[str | None] = mapped_column(String(200), nullable=True)
    refiner_disclosed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    refiner_lbma_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transport_route: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    oecd_5_step_evidence: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    lbma_rgg_step_evidence: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rjc_chain_of_custody: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dore_integrity_protocol_applicable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    high_risk_origin: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    russian_origin_exclusion_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    artisanal_source_handling: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gaps_count: Mapped[int] = mapped_column(Integer, default=0)
    gaps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    audit_readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMetalsRefinerWatch(UUIDMixin, Base):

    __tablename__ = "contractiq_metals_refiner_watch"
    __table_args__ = (
        Index("ix_ciq_metals_rw_user_refiner", "user_id", "refiner"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    refiner: Mapped[str] = mapped_column(String(200))
    lbma_gold: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lbma_silver: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lppm_platinum: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lppm_palladium: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ofac_sdn: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    next_audit_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_audit_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_contracts: Mapped[int] = mapped_column(Integer, default=0)
    last_alert: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Cross-asset capability tables ──────────────────────────────────────


class ContractIQWhatIfRun(UUIDMixin, Base):
    __tablename__ = "contractiq_whatif_runs"
    __table_args__ = (
        Index("ix_ciq_whatif_user_contract", "user_id", "contract_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="CASCADE"))
    contract_type: Mapped[str] = mapped_column(String(20))
    asset_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scenario_name: Mapped[str] = mapped_column(String(200))
    perturbations: Mapped[dict] = mapped_column(JSONB)
    base_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    scenario_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    decomposition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    calc_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQRiskRun(UUIDMixin, Base):
    __tablename__ = "contractiq_risk_runs"
    __table_args__ = (
        Index("ix_ciq_risk_user", "user_id"),
        Index("ix_ciq_risk_kind", "kind"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"))
    kind: Mapped[str] = mapped_column(String(40))  # var, cvar, portfolio_var, marginal_var, stress
    scope: Mapped[str] = mapped_column(String(20))  # single | portfolio
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_contracts.id", ondelete="SET NULL"), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.95)
    horizon_days: Mapped[int] = mapped_column(Integer, default=1)
    method: Mapped[str] = mapped_column(String(40))  # parametric | historical | filtered_historical | monte_carlo
    var_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvar_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_notional_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    drivers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tail_paths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    calc_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQRBACRole(UUIDMixin, Base):
    __tablename__ = "contractiq_rbac_roles"

    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQRBACAssignment(UUIDMixin, Base):
    __tablename__ = "contractiq_rbac_assignments"
    __table_args__ = (
        Index("ix_ciq_rbac_assign_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id", ondelete="CASCADE"))
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_rbac_roles.id", ondelete="CASCADE"))
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContractIQRule(UUIDMixin, Base):
    """One typed rule in the domain rule library — versioned, effective-dated, source-traceable."""

    __tablename__ = "contractiq_rules"
    __table_args__ = (
        Index("ix_ciq_rule_kind", "kind"),
        Index("ix_ciq_rule_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))  # penalty | payable | tc_rc | tolerance | franchise | indexation
    commodity_family: Mapped[str] = mapped_column(String(40))  # power | natgas | gold | silver | platinum | palladium | dore | concentrate
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    expression: Mapped[str] = mapped_column(Text)
    inputs_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    outputs_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | active | retired
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"), nullable=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"), nullable=True)
    source_clause_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    test_corpus: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ContractIQAuditEvent(UUIDMixin, Base):
    """Immutable audit log — every meaningful action across the platform."""

    __tablename__ = "contractiq_audit_events"
    __table_args__ = (
        Index("ix_ciq_audit_user_ts", "user_id", "created_at"),
        Index("ix_ciq_audit_kind", "kind"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    audit_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(60), nullable=True)
    calc_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMarketDataSource(UUIDMixin, Base):
    """Configurable market-data feeds. UI-managed so other apps can reuse the same registry."""

    __tablename__ = "contractiq_market_data_sources"

    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(80))
    asset_class: Mapped[str] = mapped_column(String(40))
    instrument_kind: Mapped[str] = mapped_column(String(40))  # spot | future | option | fixing | flow | rate
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractIQMarketDataPoint(UUIDMixin, Base):
    """Time-series cache of every market value pulled by the configured sources."""

    __tablename__ = "contractiq_market_data_points"
    __table_args__ = (
        Index("ix_ciq_mdp_source_ts", "source_id", "ts"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contractiq_market_data_sources.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
