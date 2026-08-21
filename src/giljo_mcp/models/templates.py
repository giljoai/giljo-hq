# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Agent template-related models for Giljo HQ.

This module contains models for agent templates, template archives,
augmentations, and usage statistics. These models support template management
and version control for agent missions.
"""

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from .base import Base, generate_uuid


def effective_last_exported_at(template: "AgentTemplate", product_export_times: dict | None = None):
    """The export time to DISPLAY for a template in a product's context (BE-9385e).

    Tolerant read, keyed on ROW EXISTENCE rather than on the value — the same
    predicate ``product_agent_selection`` uses, and for the same reason.

    ``product_export_times`` maps template id -> that product's export time for
    every junction row the product HAS, including rows whose value is still NULL.
    So:

      * id present, value set   -> this product exported it then.
      * id present, value None  -> this product has NOT exported it. Answered,
        not absent.
      * id absent (or no product in context) -> the junction has no opinion; use
        the template's tenant-wide value.

    WHY NOT "fall back whenever the value is NULL", which reads more naturally:
    the tenant-wide column is still written by every export (BE-9208's staged-ZIP
    watermark reads ``MAX(last_exported_at)``, so it cannot be frozen). A
    value-keyed fallback would therefore hand a product that never exported
    whatever timestamp ANOTHER product's export left on the shared column — the
    exact defect this project exists to remove, reintroduced through the fallback
    itself. Verified, not reasoned: with the value-keyed rule in place,
    ``test_exporting_one_product_does_not_mark_another_product_as_freshly_exported``
    still failed.

    The tenant-wide column keeps its two jobs: the fallback for products with no
    junction rows (uncurated, where selection also falls back), and pre-existing
    information that ``ce_0094`` seeds these rows from.

    Args:
        template: The agent template being displayed.
        product_export_times: Per-product export times by template id, or None
            when no product is in context.

    Returns:
        This product's export time when the junction has an opinion, else the
        template's tenant-wide time.
    """
    if product_export_times is not None and template.id in product_export_times:
        return product_export_times[template.id]
    return template.last_exported_at


class AgentTemplate(Base):
    """
    Agent Template model - stores reusable agent mission templates.
    Templates are scoped by tenant_key for multi-tenant isolation.
    Supports variable substitution and runtime augmentation.
    """

    __tablename__ = "agent_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        # BE-8000c: indexed via explicit Index("idx_template_org_id") below.
        comment="Organization for org-level templates (Handover 0424)",
    )
    product_id = Column(String(36), nullable=True)

    # Template identification
    name = Column(String(100), nullable=False)  # e.g., "orchestrator", "analyzer"
    # Default category is "role" for backward compatibility with older tests
    # and data that did not explicitly set a category.
    category = Column(
        String(50),
        nullable=False,
        default="role",
        server_default="role",
    )  # 'role', 'custom'
    role = Column(String(50), nullable=True)  # AgentRole enum value

    # Template content (Handover 0106: Dual-field system)
    system_instructions = Column(
        Text,
        nullable=False,
        default="",
        comment="Protected MCP coordination instructions (non-editable by users)",
    )
    user_instructions = Column(
        Text,
        nullable=True,
        comment="User-customizable role-specific guidance (editable)",
    )
    variables = Column(JSONB, default=list)  # List of required variables
    behavioral_rules = Column(JSONB, default=list)  # Role-specific rules
    success_criteria = Column(JSONB, default=list)  # Success metrics

    # Tool assignment (Handover 0045 - Multi-Tool Agent Orchestration)
    # BE-8000c: indexed via explicit Index("idx_template_tool") below.
    tool = Column(String(50), nullable=False, default="claude")  # AI tool: claude, codex, gemini

    # Multi-CLI Tool Support (Handover 0103)
    cli_tool = Column(
        String(20), default="claude", nullable=False
    )  # CLI tool: claude, codex, gemini, antigravity, generic
    background_color = Column(String(7))  # Hex color code for role visualization
    model = Column(String(20))  # Model selection: sonnet, opus, haiku, inherit
    tools = Column(String(50))  # Tool selection (null = inherit all)

    # Usage tracking
    avg_generation_ms = Column(Float, nullable=True)  # Performance tracking

    # Export tracking (Handover 0335)
    last_exported_at = Column(DateTime(timezone=True), nullable=True)  # Timestamp of last export to CLI
    # BE-8000c: nullable=False to match the DB/baseline (a defaulted flag is
    # never NULL); the model previously omitted it → phantom nullability drift.
    user_managed_export = Column(
        Boolean, default=False, server_default="false", nullable=False
    )  # User dismissed staleness manually

    # Metadata
    description = Column(Text, nullable=True)
    version = Column(String(20), default="1.0.0")
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)  # One default per role
    tags = Column(JSONB, default=list)
    meta_data = Column(JSONB, default=dict)

    # Soft-delete (BE-6137 — mirrors tasks.deleted_at / vision_documents.deleted_at)
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when template was soft deleted (NULL for live templates)",
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(String(100), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="templates")
    archives = relationship("TemplateArchive", back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        # BE-6137: partial unique so (name, version) is freed when a template is
        # trashed and can be reused — mirrors ce_0060 migration.
        Index(
            "uq_template_tenant_name_version",
            "tenant_key",
            "name",
            "version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_template_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_agent_templates_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_template_org_id", "org_id"),
        Index("idx_template_category", "category"),
        Index("idx_template_role", "role"),
        Index("idx_template_active", "is_active"),
        Index("idx_template_tool", "tool"),  # Handover 0045 - Tool-based filtering
        Index(
            "idx_template_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )

    def may_be_stale_against(self, last_exported_at) -> bool:
        """
        Check if this template is stale relative to a given export time.

        Four states:
        - User marked as managed → False (user dismissed staleness)
        - Never exported (last_exported_at is NULL) → True (stale)
        - Exported after last change → False (up to date)
        - Changed after last export → True (may be outdated)

        Disabled templates are never flagged as stale — the flag only matters
        when the agent is active and its outdated state is actionable.

        Falls back to created_at when updated_at is NULL (freshly seeded).

        BE-9385e: the rule lives here, taking the export time as an ARGUMENT,
        because there are now two of them — this template's tenant-wide stamp and
        the active product's own (``product_agent_assignments.last_exported_at``).
        Re-implementing four states per caller is how two callers start giving
        different answers about the same agent.

        Args:
            last_exported_at: The export time to judge against, or None for
                "never exported".
        """
        if not self.is_active:
            return False  # Disabled agents don't show staleness
        if self.user_managed_export:
            return False

        if last_exported_at is None:
            return True  # Never exported — always stale

        modified_at = self.updated_at or self.created_at
        if modified_at is None:
            return True  # No timestamp at all — assume stale

        return modified_at > last_exported_at

    @property
    def may_be_stale(self) -> bool:
        """Staleness against this template's TENANT-WIDE export stamp.

        Kept as the tenant-wide answer, and still correct wherever no product is
        in context. A product-scoped surface must resolve the effective time via
        :func:`effective_last_exported_at` first — otherwise it reports another
        product's export as its own, which is the BE-9385e defect.
        """
        return self.may_be_stale_against(self.last_exported_at)

    def __repr__(self) -> str:
        return f"<AgentTemplate(id={self.id}, name='{self.name}', category='{self.category}')>"


class TemplateArchive(Base):
    """
    Template Archive model - stores version history of templates.
    Auto-created when templates are modified for audit and rollback.
    """

    __tablename__ = "template_archives"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    template_id = Column(String(36), ForeignKey("agent_templates.id"), nullable=False)
    product_id = Column(String(36), nullable=True)

    # Archived template data (snapshot)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    role = Column(String(50), nullable=True)
    # Full system+user instructions snapshot for v3.1 dual-field support
    system_instructions = Column(Text, nullable=True)
    user_instructions = Column(Text, nullable=True)
    variables = Column(JSONB, default=list)
    behavioral_rules = Column(JSONB, default=list)
    success_criteria = Column(JSONB, default=list)

    # Archive metadata
    version = Column(String(20), nullable=False)
    archive_reason = Column(String(255), nullable=True)
    archive_type = Column(String(20), default="manual")  # 'manual', 'auto', 'scheduled'
    archived_by = Column(String(100), nullable=True)
    archived_at = Column(DateTime(timezone=True), server_default=func.now())

    # Performance snapshot
    usage_count_at_archive = Column(Integer, nullable=True)
    avg_generation_ms_at_archive = Column(Float, nullable=True)

    # Restoration tracking
    is_restorable = Column(Boolean, default=True)
    restored_at = Column(DateTime(timezone=True), nullable=True)
    restored_by = Column(String(100), nullable=True)

    # Relationships
    template = relationship("AgentTemplate", back_populates="archives")

    __table_args__ = (
        Index("idx_archive_tenant", "tenant_key"),
        Index("idx_archive_template", "template_id"),
        Index("idx_archive_product", "product_id"),
        Index("idx_archive_version", "version"),
        Index("idx_archive_date", "archived_at"),
    )

    def __repr__(self) -> str:
        return f"<TemplateArchive(id={self.id}, template_id='{self.template_id}', version={self.version})>"
