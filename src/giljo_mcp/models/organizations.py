# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class Organization(Base):

    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(String(32), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
    settings = Column(JSONB, default=dict, nullable=False)
    org_setup_complete = Column(
        Boolean, default=False, server_default="false", nullable=False
    )

    members = relationship(
        "OrgMembership",
        back_populates="organization",
        cascade="all, delete-orphan",
        order_by="OrgMembership.joined_at",
    )
    products = relationship(
        "Product",
        back_populates="organization",
        order_by="Product.created_at.desc()",
    )
    templates = relationship(
        "AgentTemplate",
        back_populates="organization",
        order_by="AgentTemplate.name",
    )
    users = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.org_id",
        order_by="User.created_at.desc()",
    )

    __table_args__ = (
        Index("idx_org_tenant", "tenant_key"),
        Index("idx_organizations_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_org_slug", "slug", unique=True),
        Index("idx_org_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name='{self.name}', slug='{self.slug}')>"


class OrgMembership(Base):

    __tablename__ = "org_memberships"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_key = Column(String(36), nullable=False)
    role = Column(
        String(32),
        nullable=False,
        default="member",
    )
    is_active = Column(Boolean, default=True, nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    invited_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    organization = relationship("Organization", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], backref="org_memberships")
    inviter = relationship("User", foreign_keys=[invited_by])

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_user"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_membership_role",
        ),
        Index("idx_membership_user", "user_id"),
        Index("idx_membership_tenant", "tenant_key"),
    )

    def __repr__(self) -> str:
        return f"<OrgMembership(id={self.id}, org_id='{self.org_id}', user_id='{self.user_id}', role='{self.role}')>"
