import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class UserMCPConnection(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "user_mcp_connections"
    __table_args__ = (Index("ix_mcp_conn_tenant_user", "tenant_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    server_name: Mapped[str] = mapped_column(String(255))
    server_url: Mapped[str] = mapped_column(String(1000))
    transport_type: Mapped[str] = mapped_column(String(50), default="stdio")
    auth_type: Mapped[str] = mapped_column(String(50), default="none")
    auth_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    discovered_tools: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    health_status: Mapped[str] = mapped_column(String(50), default="unknown")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    oauth2_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth2_authorization_url: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    oauth2_token_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    oauth2_access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth2_refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth2_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agent_tools: Mapped[list["AgentMCPTool"]] = relationship(
        back_populates="mcp_connection"
    )


class AgentMCPTool(UUIDMixin, Base):
    __tablename__ = "agent_mcp_tools"
    __table_args__ = (
        Index("ix_agent_mcp_tools_agent", "agent_id", "mcp_connection_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    mcp_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_mcp_connections.id"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(255))
    tool_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    max_calls_per_execution: Mapped[int | None] = mapped_column(Integer, nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="mcp_tools")
    mcp_connection: Mapped["UserMCPConnection"] = relationship(
        back_populates="agent_tools"
    )


class MCPRegistryCache(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "mcp_registry_cache"

    registry_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    server_url: Mapped[str] = mapped_column(String(1000))
    auth_type: Mapped[str] = mapped_column(String(50), default="none")
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tools_count: Mapped[int] = mapped_column(Integer, default=0)
    popularity_score: Mapped[float] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


from models.agent import Agent  # noqa: E402
