# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Organization-related models for Giljo HQ.

This module contains models for organizations and organization memberships.
Organizations provide a hierarchical tenant structure above products.

Handover 0424a: Organization Database Schema
"""

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
    """
    Organization model - hierarchical tenant structure above products.

    Organizations provide multi-user collaboration and resource sharing.
    Each organization can have multiple users (via memberships) and own
    multiple products, templates, and tasks.

    Handover 0424a: Organization Database Schema
    """

    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: indexed via explicit Index("idx_org_tenant") below.
    tenant_key = Column(String(36), nullable=False)  # ADDED: Multi-tenant isolation (0424m)
    name = Column(String(255), nullable=False)
    # BE-8000c: uniqueness+index via explicit Index("idx_org_slug", unique=True)
    # below; no column-level unique/index=True (that added a duplicate ix_* twin).
    slug = Column(String(255), nullable=False)  # FIXED: 100 -> 255 (0424m)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(String(32), nullable=True)  # Ops panel soft-delete status (ce_0001)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Timestamp for soft-delete grace period (ce_0002)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=True,  # FIXED: Remove server_default and onupdate (0424m)
    )
    settings = Column(JSONB, default=dict, nullable=False)
    org_setup_complete = Column(
        Boolean, default=False, server_default="false", nullable=False
    )  # First-login org setup wizard completion flag

    # Relationships
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
    # Direct User relationship (Handover 0424f)
    users = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.org_id",
        order_by="User.created_at.desc()",
    )

    __table_args__ = (
        Index("idx_org_tenant", "tenant_key"),  # Match migration name (0424m)
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_organizations_tenant_updated", "tenant_key", "updated_at"),
        Index("idx_org_slug", "slug", unique=True),  # Match migration name (0424m)
        Index("idx_org_active", "is_active"),  # Match migration name (0424m)
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name='{self.name}', slug='{self.slug}')>"


class OrgMembership(Base):
    """
    Organization Membership model - links users to organizations with roles.

    Defines user roles within an organization:
    - owner: Full control, can delete organization
    - admin: Manage users, products, settings
    - member: Create and manage own products
    - viewer: Read-only access

    Handover 0424a: Organization Database Schema
    """

    __tablename__ = "org_memberships"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: org_id indexed by uq_org_user (org_id, user_id) leftmost — the
    # redundant idx_membership_org was dropped; user_id/tenant_key indexed via
    # the explicit Index(...) entries below (no column-level index=True).
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
    tenant_key = Column(String(36), nullable=False)  # ADDED: Multi-tenant isolation (0424m)
    role = Column(
        String(32),
        nullable=False,
        default="member",  # FIXED: 20 -> 32 (0424m)
    )  # owner, admin, member, viewer
    is_active = Column(Boolean, default=True, nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    invited_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], backref="org_memberships")
    inviter = relationship("User", foreign_keys=[invited_by])

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_user"),  # FIXED: Match migration (0424m)
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_membership_role",  # FIXED: Match migration (0424m)
        ),
        # BE-8000c: idx_membership_org dropped — leftmost-covered by uq_org_user
        # (org_id, user_id). The org/Teams scaffolding itself is UNTOUCHED (ADR-009).
        Index("idx_membership_user", "user_id"),  # FIXED: Match migration (0424m)
        Index("idx_membership_tenant", "tenant_key"),  # ADDED: Match migration (0424m)
    )

    def __repr__(self) -> str:
        return f"<OrgMembership(id={self.id}, org_id='{self.org_id}', user_id='{self.user_id}', role='{self.role}')>"
