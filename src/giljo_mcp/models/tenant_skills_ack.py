# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.sql import func

from .base import Base


class TenantSkillsAck(Base):

    __tablename__ = "tenant_skills_ack"

    tenant_key = Column(String(255), primary_key=True)
    acknowledged_version = Column(String(128), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_tenant_skills_ack_tenant_updated", "tenant_key", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<TenantSkillsAck(tenant_key={self.tenant_key!r}, acknowledged_version={self.acknowledged_version!r})>"
