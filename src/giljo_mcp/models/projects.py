# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    case,
    literal,
    select,
    text,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import column_property, relationship
from sqlalchemy.sql import func

from giljo_mcp.domain.project_status import ProjectStatus

from .base import Base, generate_project_alias, generate_uuid


class TaxonomyType(Base):

    __tablename__ = "taxonomy_types"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    abbreviation = Column(
        String(4),
        nullable=False,
        comment="2-4 uppercase letter abbreviation (e.g., BE, FE, API)",
    )
    label = Column(String(50), nullable=False, comment="Human-readable label (e.g., Backend, Frontend)")
    color = Column(String(7), nullable=False, default="#607D8B", comment="Hex color for UI display")
    sort_order = Column(Integer, default=0, comment="Display ordering in UI dropdowns")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    projects = relationship("Project", back_populates="project_type")

    __table_args__ = (
        UniqueConstraint("tenant_key", "abbreviation", name="uq_taxonomy_type_abbr"),
        Index("idx_taxonomy_types_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<TaxonomyType(id={self.id}, abbreviation='{self.abbreviation}', label='{self.label}')>"


class Project(Base):

    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    alias = Column(
        String(6),
        nullable=False,
        unique=True,
        index=True,
        default=generate_project_alias,
        comment="6-character alphanumeric project identifier (e.g., A1B2C3)",
    )

    description = Column(Text, nullable=False)

    mission = Column(Text, nullable=False)
    status = Column(
        SQLAlchemyEnum(
            ProjectStatus,
            name="project_status",
            native_enum=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ProjectStatus.INACTIVE,
        server_default=text("'inactive'::project_status"),
    )

    staging_status = Column(
        String(50),
        nullable=True,
        comment="Staging workflow status: null (not staged), staging (in progress), or staging_complete",
    )

    project_type_id = Column(
        String(36),
        ForeignKey("taxonomy_types.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to taxonomy_types for taxonomy classification",
    )
    series_number = Column(
        Integer,
        nullable=True,
        comment="Sequential number within a project type (e.g., 1 in BE-0001)",
    )
    subseries = Column(
        String(1),
        nullable=True,
        comment="Single-letter subseries suffix (e.g., 'a' in BE-0001a)",
    )

    hidden = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Whether project is hidden from default list view",
    )

    successor_project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to the project that supersedes this one (audit trail for replaced work)",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    implementation_launched_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp when user clicked Implement button. NULL = staging only.",
    )
    ever_launched_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment=(
            "First time this project EVER crossed the Implement gate. Set once, "
            "never overwritten by re-launch. Survives restage (audit-preserving); "
            "cleared only by reset_to_prestage (discard-everything rewind). Powers "
            "the BE-9085 pre-launch-workproduct detector's restage false-positive "
            "suppression."
        ),
    )
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when project was soft deleted (NULL for active projects)",
    )
    cancellation_reason = Column(Text, nullable=True, comment="Reason for project cancellation")
    early_termination = Column(
        Boolean,
        nullable=True,
        default=False,
        server_default=text("false"),
        comment="Whether project was terminated early via termination prompt",
    )

    orchestrator_summary = Column(
        Text, nullable=True, comment="AI-generated final summary of project outcomes and deliverables"
    )
    closeout_prompt = Column(
        Text, nullable=True, comment="Prompt template used by orchestrator for closeout generation"
    )
    closeout_executed_at = Column(
        DateTime(timezone=True), nullable=True, comment="Timestamp when closeout workflow was executed"
    )
    closeout_checklist = Column(
        JSONB,
        default=list,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="Structured checklist of closeout tasks (JSONB array)",
    )

    execution_mode = Column(
        String(20),
        nullable=True,
        comment=(
            "Execution mode: 'multi_terminal' | 'subagent' (legacy per-CLI tokens tolerated); NULL = not yet selected"
        ),
    )

    auto_checkin_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Enable orchestrator self-polling in multi-terminal mode",
    )
    auto_checkin_interval = Column(
        Integer,
        nullable=False,
        default=10,
        server_default=text("10"),
        comment="Auto check-in interval in minutes (5, 10, 15, 20, 30, 40, 60)",
    )

    product = relationship("Product", back_populates="projects")
    project_type = relationship("TaxonomyType", back_populates="projects")
    agent_jobs_v2 = relationship("AgentJob", back_populates="project", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship(
        "Task", foreign_keys="Task.project_id", back_populates="project", cascade="all, delete-orphan"
    )
    memory_entries = relationship("ProductMemoryEntry", back_populates="project")

    __table_args__ = (
        Index(
            "uq_project_taxonomy_active",
            "tenant_key",
            "product_id",
            "project_type_id",
            "series_number",
            "subseries",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_project_tenant", "tenant_key"),
        Index("idx_projects_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_project_status", "status"),
        Index(
            "idx_projects_tenant_created",
            "tenant_key",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_projects_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
        Index(
            "idx_projects_closeout_executed",
            "closeout_executed_at",
            postgresql_where=text("closeout_executed_at IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}', product_id='{self.product_id}')>"


_project_abbr_subq = (
    select(TaxonomyType.abbreviation)
    .where(
        TaxonomyType.id == Project.project_type_id,
        TaxonomyType.tenant_key == Project.tenant_key,
    )
    .correlate(Project)
    .scalar_subquery()
)

Project.taxonomy_alias = column_property(
    case(
        (
            and_(Project.project_type_id.is_(None), Project.series_number.is_(None)),
            Project.alias,
        ),
        (
            Project.series_number.is_(None),
            func.coalesce(_project_abbr_subq, literal("")),
        ),
        else_=(
            func.coalesce(_project_abbr_subq, literal(""))
            + case(
                (func.nullif(_project_abbr_subq, literal("")).is_not(None), literal("-")),
                else_=literal(""),
            )
            + func.lpad(
                func.cast(Project.series_number, String),
                func.greatest(literal(4), func.length(func.cast(Project.series_number, String))),
                literal("0"),
            )
            + func.coalesce(Project.subseries, literal(""))
        ),
    ),
    deferred=False,
)
