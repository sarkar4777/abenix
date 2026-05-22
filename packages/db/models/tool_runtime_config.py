"""Per-tool runtime knobs — cache, semaphore, rate-limit, circuit breaker, pool."""

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class ToolRuntimeConfig(Base, TimestampMixin):
    """Single row per tool slug. Org-wide config, NOT per-tenant.

    Why org-wide: external API rate limits (Yahoo, LBMA, Tavily) apply to
    the WHOLE platform, not per tenant. Per-tenant fairness is enforced by
    `*_per_tenant` fields layered on top of the global cap.
    """

    __tablename__ = "tool_runtime_config"

    slug: Mapped[str] = mapped_column(String(120), primary_key=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pool: Mapped[str] = mapped_column(String(20), default="inline", nullable=False)

    max_inflight_global: Mapped[int] = mapped_column(
        Integer, default=50, nullable=False
    )
    max_inflight_per_tenant: Mapped[int] = mapped_column(
        Integer, default=20, nullable=False
    )

    rate_limit_qps_global: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    rate_limit_qps_per_tenant: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    cache_ttl_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_scope: Mapped[str] = mapped_column(
        String(20), default="global", nullable=False
    )

    circuit_breaker_threshold: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    circuit_breaker_window_s: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )
    circuit_breaker_cooldown_s: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )

    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    daily_budget_calls_per_tenant: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
