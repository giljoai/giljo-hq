# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base


class ProductMemoryEntry(Base):

    __tablename__ = "product_memory_entries"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="Unique entry identifier",
    )

    tenant_key = Column(
        String(36),
        nullable=False,
        comment="Tenant isolation key",
    )

    product_id = Column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent product (CASCADE on delete)",
    )
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        comment="Source project (SET NULL on delete - preserves history)",
    )

    sequence = Column(
        Integer,
        nullable=False,
        comment="Sequence number within product (1-based)",
    )
    entry_type = Column(
        String(50),
        nullable=False,
        comment=(
            "Entry type. Validated as a frozenset in write_360_memory.py "
            "(no DB constraint), on WRITE only. Currently admitted: "
            "project_completion (orchestrator project closeout); "
            "baseline (initial seeding -- architecture snapshot, foundation context); "
            "decision (a specific choice with rationale); "
            "architecture (structural notes about the system); "
            "discovery (surprising finding worth remembering). "
            "Stored rows may also carry handover_closeout or session_handover, which "
            "BE-9637 stopped accepting when handovers became HND tasks; those entries "
            "are read and rendered normally and were deliberately not migrated."
        ),
    )
    source = Column(
        String(50),
        nullable=False,
        comment="Source tool: closeout_v1, write_360_memory_v1, migration_backfill",
    )
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the entry was created",
    )

    project_name = Column(
        String(255),
        nullable=True,
        comment="Project name at time of entry",
    )
    summary = Column(
        Text,
        nullable=True,
        comment="2-3 paragraph summary of work accomplished",
    )
    key_outcomes = Column(
        JSONB,
        default=list,
        server_default="[]",
        comment="List of key achievements",
    )
    decisions_made = Column(
        JSONB,
        default=list,
        server_default="[]",
        comment="List of architectural/design decisions",
    )
    git_commits = Column(
        JSONB,
        default=list,
        server_default="[]",
        comment="List of git commit objects with sha, message, author",
    )

    deliverables = Column(
        JSONB,
        default=list,
        server_default="[]",
        comment="List of files/artifacts delivered",
    )
    metrics = Column(
        JSONB,
        default=dict,
        server_default="{}",
        comment="Metrics dict (test_coverage, etc.)",
    )
    priority = Column(
        Integer,
        default=3,
        server_default="3",
        comment="Priority level 1-5",
    )
    significance_score = Column(
        Float,
        default=0.5,
        server_default="0.5",
        comment="Significance score 0.0-1.0",
    )
    token_estimate = Column(
        Integer,
        nullable=True,
        comment="Estimated tokens for this entry",
    )
    tags = Column(
        JSONB,
        default=list,
        server_default="[]",
        comment="List of tags for categorization",
    )

    author_job_id = Column(
        String(36),
        nullable=True,
        comment="Job ID of agent that wrote this entry",
    )
    author_name = Column(
        String(255),
        nullable=True,
        comment="Name of agent that wrote this entry",
    )
    author_type = Column(
        String(50),
        nullable=True,
        comment="Type of agent (orchestrator, implementer, etc.)",
    )

    deleted_by_user = Column(
        Boolean,
        default=False,
        server_default="false",
        comment="True if source project was deleted by user",
    )
    user_deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the source project was deleted",
    )

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        comment="When this row was created",
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="When this row was last updated",
    )

    product = relationship("Product", back_populates="memory_entries")
    project = relationship("Project", back_populates="memory_entries")

    __table_args__ = (
        UniqueConstraint("product_id", "sequence", name="uq_product_sequence"),
        Index("idx_pme_tenant_product", "tenant_key", "product_id"),
        Index("idx_pme_project", "project_id", postgresql_where="project_id IS NOT NULL"),
        Index("idx_pme_tenant_timestamp", "tenant_key", text("timestamp DESC")),
        Index("idx_product_memory_entries_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_pme_type", "entry_type"),
        Index("idx_pme_deleted", "deleted_by_user", postgresql_where="deleted_by_user = true"),
    )

    def __repr__(self) -> str:
        return f"<ProductMemoryEntry(id={self.id}, product_id={self.product_id}, sequence={self.sequence}, type={self.entry_type})>"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "sequence": self.sequence,
            "project_id": str(self.project_id) if self.project_id else None,
            "project_name": self.project_name,
            "type": self.entry_type,
            "source": self.source,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "summary": self.summary,
            "key_outcomes": self.key_outcomes or [],
            "decisions_made": self.decisions_made or [],
            "git_commits": self.git_commits or [],
            "deliverables": self.deliverables or [],
            "metrics": self.metrics or {},
            "priority": self.priority,
            "significance_score": self.significance_score,
            "token_estimate": self.token_estimate,
            "tags": self.tags or [],
            "author_job_id": str(self.author_job_id) if self.author_job_id else None,
            "author_name": self.author_name,
            "author_type": self.author_type,
            "deleted_by_user": self.deleted_by_user,
            "user_deleted_at": self.user_deleted_at.isoformat() if self.user_deleted_at else None,
        }
