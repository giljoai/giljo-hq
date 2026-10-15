# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class TemplateProposal(Base):

    __tablename__ = "template_proposals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    target_kind = Column(String(32), nullable=False)
    slot_key = Column(String(80), nullable=False)
    template_id = Column(String(36), ForeignKey("agent_templates.id", ondelete="CASCADE"), nullable=True)
    product_id = Column(String(36), nullable=True)
    rung = Column(String(16), nullable=True)
    proposed_text = Column(Text, nullable=False)
    reason = Column(String(500), nullable=False)
    proposed_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    replaced_note = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_key", "slot_key", name="uq_template_proposal_tenant_slot"),
        Index("idx_template_proposal_tenant", "tenant_key"),
    )

    def __repr__(self) -> str:
        return f"<TemplateProposal(id={self.id}, slot_key='{self.slot_key}')>"
