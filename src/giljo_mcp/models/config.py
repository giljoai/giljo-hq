# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class Configuration(Base):

    __tablename__ = "configurations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    key = Column(String(255), nullable=False)
    value = Column(JSONB, nullable=False)
    category = Column(String(100), default="general")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_key", "key", name="uq_config_tenant_key"),
        Index("idx_config_category", "category"),
        Index("idx_configurations_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Configuration(id={self.id}, key='{self.key}', category='{self.category}')>"


class SetupState(Base):

    __tablename__ = "setup_state"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False, unique=True, index=True)

    database_initialized = Column(Boolean, default=False, nullable=False)
    database_initialized_at = Column(DateTime(timezone=True), nullable=True)

    setup_version = Column(String(20), nullable=True)
    python_version = Column(String(20), nullable=True)


    first_admin_created = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="True after first admin account created - prevents duplicate admin creation attacks",
    )
    first_admin_created_at = Column(
        DateTime(timezone=True), nullable=True, comment="Timestamp when first admin account was created"
    )

    validation_failures = Column(JSONB, default=list, nullable=False, comment="Array of validation failure messages")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "setup_version IS NULL OR setup_version ~ '^[0-9]+\\.[0-9]+\\.[0-9]+(-[a-zA-Z0-9\\.\\-]+)?$'",
            name="ck_setup_version_format",
        ),
        CheckConstraint(
            "(database_initialized = false) OR (database_initialized = true AND database_initialized_at IS NOT NULL)",
            name="ck_database_initialized_at_required",
        ),
        CheckConstraint(
            "(first_admin_created = false) OR (first_admin_created = true AND first_admin_created_at IS NOT NULL)",
            name="ck_first_admin_created_at_required",
        ),
        Index("idx_setup_database_initialized", "database_initialized"),
        Index("idx_setup_state_tenant_updated", "tenant_key", "updated_at"),
        Index(
            "idx_setup_database_incomplete",
            "tenant_key",
            "database_initialized",
            postgresql_where="database_initialized = false",
        ),
        Index(
            "idx_setup_fresh_install",
            "tenant_key",
            "first_admin_created",
            postgresql_where="first_admin_created = false",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_key": self.tenant_key,
            "database_initialized": self.database_initialized,
            "database_initialized_at": self.database_initialized_at.isoformat()
            if self.database_initialized_at
            else None,
            "setup_version": self.setup_version,
            "python_version": self.python_version,
            "first_admin_created": self.first_admin_created,
            "first_admin_created_at": self.first_admin_created_at.isoformat() if self.first_admin_created_at else None,
            "validation_failures": self.validation_failures,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    async def get_by_tenant(cls, session: AsyncSession, tenant_key: str) -> SetupState | None:
        from sqlalchemy import select

        result = await session.execute(select(cls).where(cls.tenant_key == tenant_key))
        return result.scalar_one_or_none()

    _ALLOWED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "database_initialized",
            "database_initialized_at",
            "setup_version",
            "python_version",
            "first_admin_created",
            "first_admin_created_at",
            "validation_failures",
        }
    )

    @classmethod
    def create_or_update(cls, session: Session, tenant_key: str, **kwargs) -> SetupState:
        safe_kwargs = {k: v for k, v in kwargs.items() if k in cls._ALLOWED_FIELDS}

        state = cls.get_by_tenant(session, tenant_key)

        if state:
            for key, value in safe_kwargs.items():
                setattr(state, key, value)
        else:
            state = cls(tenant_key=tenant_key, **safe_kwargs)
            session.add(state)

        session.flush()
        return state

    def __repr__(self) -> str:
        return f"<SetupState(id={self.id}, tenant_key='{self.tenant_key}', db_initialized={self.database_initialized})>"


class DownloadToken(Base):

    __tablename__ = "download_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(
        String(36),
        unique=True,
        nullable=False,
        default=generate_uuid,
        index=True,
        comment="UUID v4 token used in download URL",
    )
    tenant_key = Column(String(36), nullable=False, comment="Tenant key for multi-tenant isolation")

    download_type = Column(
        String(50),
        nullable=False,
        comment="Type of download: 'slash_commands', 'agent_templates', 'tenant_export'",
    )
    filename = Column(String(255), nullable=True, comment="Original filename for the download")

    staging_status = Column(
        String(20), default="pending", nullable=False, comment="Staging lifecycle status: pending|ready|failed"
    )
    staging_error = Column(Text, nullable=True, comment="Staging error details when status=failed")
    download_count = Column(Integer, default=0, nullable=False, comment="Number of successful downloads for this token")
    last_downloaded_at = Column(
        DateTime(timezone=True), nullable=True, comment="Timestamp of most recent successful download"
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(
        DateTime(timezone=True), nullable=False, comment="Token expiry timestamp (15 minutes after creation)"
    )
    staged_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="TSK-9210: when this token's ZIP was staged; anchors per-token staleness",
    )

    __table_args__ = (
        Index("idx_download_token_expires", "expires_at"),
        Index("idx_download_token_tenant_type", "tenant_key", "download_type"),
        CheckConstraint(
            "download_type IN ('slash_commands', 'agent_templates', 'tenant_export')",
            name="ck_download_token_type",
        ),
        CheckConstraint("staging_status IN ('pending', 'ready', 'failed')", name="ck_download_token_staging_status"),
    )

    def __repr__(self) -> str:
        return f"<DownloadToken(id={self.id}, token={self.token}, type={self.download_type}, downloads={self.download_count})>"

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    @property
    def is_valid(self) -> bool:
        return (not self.is_expired) and (self.staging_status == "ready")


class ApiMetrics(Base):

    __tablename__ = "api_metrics"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False, unique=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    total_api_calls = Column(Integer, default=0)
    total_mcp_calls = Column(Integer, default=0)

    __table_args__ = (Index("idx_api_metrics_tenant_date", "tenant_key", "date"),)

    def __repr__(self) -> str:
        return f"<ApiMetrics(id={self.id}, tenant_key='{self.tenant_key}')>"
