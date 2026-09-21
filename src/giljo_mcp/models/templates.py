# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


class AgentTemplate(Base):

    __tablename__ = "agent_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        comment="Organization for org-level templates (Handover 0424)",
    )
    product_id = Column(String(36), nullable=True)

    name = Column(String(100), nullable=False)
    category = Column(
        String(50),
        nullable=False,
        default="role",
        server_default="role",
    )
    role = Column(String(50), nullable=True)

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
    variables = Column(JSONB, default=list)
    behavioral_rules = Column(JSONB, default=list)
    success_criteria = Column(JSONB, default=list)

    tool = Column(String(50), nullable=False, default="claude")

    cli_tool = Column(
        String(20), default="claude", nullable=False
    )
    background_color = Column(String(7))
    model = Column(String(120), nullable=True, default="inherit")
    effort = Column(String(120), nullable=False, default="inherit", server_default="inherit")
    tools = Column(String(50))

    avg_generation_ms = Column(Float, nullable=True)

    description = Column(Text, nullable=True)
    version = Column(String(20), default="1.0.0")
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    tags = Column(JSONB, default=list)
    meta_data = Column(JSONB, default=dict)

    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when template was soft deleted (NULL for live templates)",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(String(100), nullable=True)

    organization = relationship("Organization", back_populates="templates")
    archives = relationship("TemplateArchive", back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "uq_template_tenant_name_version",
            "tenant_key",
            "name",
            "version",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_template_tenant", "tenant_key"),
        Index("idx_template_tenant_product", "tenant_key", "product_id"),
        Index("idx_agent_templates_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_template_org_id", "org_id"),
        Index("idx_template_category", "category"),
        Index("idx_template_role", "role"),
        Index("idx_template_active", "is_active"),
        Index("idx_template_tool", "tool"),
        Index(
            "idx_template_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentTemplate(id={self.id}, name='{self.name}', category='{self.category}')>"


class TemplateArchive(Base):

    __tablename__ = "template_archives"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    template_id = Column(String(36), ForeignKey("agent_templates.id"), nullable=False)
    product_id = Column(String(36), nullable=True)

    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    role = Column(String(50), nullable=True)
    system_instructions = Column(Text, nullable=True)
    user_instructions = Column(Text, nullable=True)
    variables = Column(JSONB, default=list)
    behavioral_rules = Column(JSONB, default=list)
    success_criteria = Column(JSONB, default=list)

    version = Column(String(20), nullable=False)
    archive_reason = Column(String(255), nullable=True)
    archive_type = Column(String(20), default="manual")
    archived_by = Column(String(100), nullable=True)
    archived_at = Column(DateTime(timezone=True), server_default=func.now())

    usage_count_at_archive = Column(Integer, nullable=True)
    avg_generation_ms_at_archive = Column(Float, nullable=True)

    is_restorable = Column(Boolean, default=True)
    restored_at = Column(DateTime(timezone=True), nullable=True)
    restored_by = Column(String(100), nullable=True)

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
