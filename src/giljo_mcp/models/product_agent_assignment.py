# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductAgentAssignment model - lightweight per-product agent toggle.

Templates belong to the tenant; products reference which ones are active.
Think Spotify: songs exist once, playlists point to them.

This junction table lets each product independently choose which agent
templates are active without duplicating template data.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class ProductAgentAssignment(Base):
    """
    Junction table linking products to agent templates.

    Each row represents a product's reference to a tenant-wide template,
    with an is_active toggle to enable/disable per product.

    Tenant isolation: Every query MUST filter by tenant_key.
    """

    __tablename__ = "product_agent_assignments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id = Column(
        String(36),
        ForeignKey("agent_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    tenant_key = Column(String(36), nullable=False)

    # BE-9385e: when THIS product last exported this agent.
    #
    # ``agent_templates.last_exported_at`` is tenant-wide, so exporting product A
    # stamped a column product B then read as its own -- the staleness indicator
    # reported another product's action as this product's state. This column is
    # the per-product truth; the tenant-wide one stays as the fallback for rows
    # this project's backfill did not reach and as pre-existing information.
    #
    # NULL means "no per-product record yet", NOT "never exported" -- the read
    # falls back to the template's value. Only an export writes it here, and only
    # for the product that did the exporting.
    last_exported_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    product = relationship("Product", back_populates="agent_assignments")
    # BE-9531: this was a bare backref="product_assignments". With no cascade,
    # SQLAlchemy's default on parent delete is to load the children and null
    # their FK -- into template_id's nullable=False. The database FK is already
    # ON DELETE CASCADE, so passive_deletes hands the work to the database that
    # was always going to do it correctly. Matches Product.agent_assignments,
    # which was declared this way from the start and never had the defect.
    template = relationship(
        "AgentTemplate",
        backref=backref("product_assignments", cascade="all, delete-orphan", passive_deletes=True),
    )

    __table_args__ = (
        # BE-8000c: idx_assignment_product dropped — leftmost-covered by
        # uq_product_template_assignment (product_id, template_id).
        UniqueConstraint("product_id", "template_id", name="uq_product_template_assignment"),
        Index("idx_assignment_tenant", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_product_agent_assignments_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_assignment_template", "template_id"),
        Index("idx_assignment_active", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProductAgentAssignment(id={self.id}, product_id='{self.product_id}', "
            f"template_id='{self.template_id}', is_active={self.is_active})>"
        )
