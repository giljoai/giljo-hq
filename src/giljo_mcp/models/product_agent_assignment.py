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
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class ProductAgentAssignment(Base):

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

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="agent_assignments")
    template = relationship(
        "AgentTemplate",
        backref=backref("product_assignments", cascade="all, delete-orphan", passive_deletes=True),
    )

    __table_args__ = (
        UniqueConstraint("product_id", "template_id", name="uq_product_template_assignment"),
        Index("idx_assignment_tenant", "tenant_key"),
        Index("idx_product_agent_assignments_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_assignment_template", "template_id"),
        Index("idx_assignment_active", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProductAgentAssignment(id={self.id}, product_id='{self.product_id}', "
            f"template_id='{self.template_id}', is_active={self.is_active})>"
        )
