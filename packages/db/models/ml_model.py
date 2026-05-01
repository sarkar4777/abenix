"""ML Model Registry — store, version, deploy, and serve ML models."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class MLModelFramework(str, enum.Enum):
    SKLEARN = "sklearn"
    PYTORCH = "pytorch"
    ONNX = "onnx"
    TENSORFLOW = "tensorflow"
    XGBOOST = "xgboost"
    CUSTOM = "custom"


class MLModelStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    READY = "ready"
    ERROR = "error"
    DELETED = "deleted"


class DeploymentType(str, enum.Enum):
    LOCAL = "local"
    K8S = "k8s"


class DeploymentStatus(str, enum.Enum):
    DEPLOYING = "deploying"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class MLModel(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A registered ML model available for inference via the ml_model tool."""

    __tablename__ = "ml_models"
    __table_args__ = (
        Index("ix_ml_models_tenant_name", "tenant_id", "name"),
        Index("ix_ml_models_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    framework: Mapped[MLModelFramework] = mapped_column(
        Enum(
            MLModelFramework,
            name="ml_model_framework",
            values_callable=lambda e: [m.value for m in e],
        ),
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Storage
    file_uri: Mapped[str] = mapped_column(String(1000))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Schema — describes what the model accepts and returns
    input_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # e.g. {"features": ["sepal_length", "sepal_width", "petal_length", "petal_width"], "types": ["float"]*4}
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # e.g. {"type": "classification", "classes": ["setosa", "versicolor", "virginica"]}

    # Metadata
    status: Mapped[MLModelStatus] = mapped_column(
        Enum(
            MLModelStatus,
            name="ml_model_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=MLModelStatus.UPLOADED,
    )
    training_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # e.g. {"accuracy": 0.97, "f1": 0.96, "training_samples": 150}

    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # e.g. ["iris", "classifier", "demo"]

    # Versioning: only ONE version of a given name can be active per tenant.
    # When an agent calls predict(model_name="iris"), the active version is used.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    # Relationships
    deployments: Mapped[list["MLModelDeployment"]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
    )


class MLModelDeployment(UUIDMixin, TimestampMixin, Base):
    """A running deployment of an ML model (in-process or k8s pod)."""

    __tablename__ = "ml_model_deployments"
    __table_args__ = (
        Index("ix_ml_deployments_model", "model_id"),
        Index("ix_ml_deployments_status", "status"),
    )

    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ml_models.id", ondelete="CASCADE"),
    )
    deployment_type: Mapped[DeploymentType] = mapped_column(
        Enum(
            DeploymentType,
            name="deployment_type",
            values_callable=lambda e: [m.value for m in e],
        ),
    )
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    replicas: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[DeploymentStatus] = mapped_column(
        Enum(
            DeploymentStatus,
            name="deployment_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DeploymentStatus.DEPLOYING,
    )

    # K8s metadata
    pod_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    k8s_namespace: Mapped[str] = mapped_column(String(100), default="abenix")
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationship
    model: Mapped[MLModel] = relationship(back_populates="deployments")
