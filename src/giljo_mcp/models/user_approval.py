# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from .base import Base, generate_uuid


VALID_USER_APPROVAL_STATUSES = ("pending", "decided", "expired", "cancelled")


class UserApproval(Base):

    __tablename__ = "user_approvals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(50), nullable=False)

    agent_execution_id = Column(
        String(36),
        ForeignKey("agent_executions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id = Column(
        String(36),
        ForeignKey("agent_jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )

    reason = Column(Text, nullable=False)
    options = Column(JSONB, nullable=False)
    context = Column(JSONB, nullable=True)

    status = Column(String(20), nullable=False, default="pending")
    decided_option_id = Column(String(100), nullable=True)
    decided_by_user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_via = Column(
        String(10),
        nullable=True,
        comment="BE-9514: which door decided this ('ui' | 'mcp'); NULL for legacy rows predating the column",
    )

    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    decided_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_user_approvals_tenant_status", "tenant_key", "status"),
        Index("ix_user_approvals_agent_status", "agent_execution_id", "status"),
        CheckConstraint(
            "status IN ('pending', 'decided', 'expired', 'cancelled')",
            name="ck_user_approvals_status",
        ),
        CheckConstraint(
            "decided_via IS NULL OR decided_via IN ('ui', 'mcp')",
            name="ck_user_approvals_decided_via",
        ),
    )

    def __repr__(self) -> str:
        return f"<UserApproval(id={self.id}, status={self.status}, agent_execution_id={self.agent_execution_id})>"
