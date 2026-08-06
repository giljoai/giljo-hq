# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
OrgRepository - Data access layer for Organization and OrgMembership entities.

BE-5022c: Extracted from org_service.py to enforce the service->repository
boundary. All database reads and writes for Organization and OrgMembership
are routed through this repository.

Tenant isolation: All query methods accept tenant_key and apply it when
provided. Callers SHOULD always pass tenant_key; None is accepted only for
backward compatibility during incremental migration.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.organizations import Organization, OrgMembership


logger = logging.getLogger(__name__)


class OrgRepository:
    """
    Repository for organization-domain database operations.

    Methods accept an AsyncSession parameter (session-in pattern) so the
    calling service controls transaction boundaries.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ========================================================================
    # Organization CRUD
    # ========================================================================

    async def add_organization(self, session: AsyncSession, org: Organization) -> Organization:
        """
        Add an organization and flush to obtain org.id.

        Args:
            session: Active database session
            org: Fully constructed Organization ORM instance

        Returns:
            Organization with generated id
        """
        session.add(org)
        await session.flush()
        return org

    async def get_organization_by_id(
        self,
        session: AsyncSession,
        org_id: str,
        tenant_key: str | None = None,
        active_only: bool = True,
    ) -> Organization | None:
        """
        Get organization by ID with eagerly loaded members.

        Args:
            session: Active database session
            org_id: Organization UUID
            tenant_key: Tenant isolation key (should always be provided)
            active_only: If True, only return active organizations

        Returns:
            Organization ORM instance or None
        """
        stmt = select(Organization).where(Organization.id == org_id)
        if tenant_key is not None:
            stmt = stmt.where(Organization.tenant_key == tenant_key)
        if active_only:
            stmt = stmt.where(Organization.is_active)
        stmt = stmt.options(selectinload(Organization.members))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_organization_by_slug(
        self, session: AsyncSession, slug: str, tenant_key: str | None = None
    ) -> Organization | None:
        """
        Get organization by slug with eagerly loaded members.

        Args:
            session: Active database session
            slug: Organization slug
            tenant_key: Tenant isolation key (should always be provided)

        Returns:
            Organization ORM instance or None
        """
        stmt = select(Organization).where(Organization.slug == slug)
        if tenant_key is not None:
            stmt = stmt.where(Organization.tenant_key == tenant_key)
        stmt = stmt.options(selectinload(Organization.members))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def slug_taken_by_other_org(self, session: AsyncSession, slug: str, exclude_org_id: str) -> bool:
        """
        Return True if an organization other than ``exclude_org_id`` owns ``slug``.

        The ``slug`` column is globally unique on ``organizations`` (not scoped
        by tenant), so the uniqueness check here intentionally does not filter
        by tenant_key. Callers pass ``exclude_org_id`` so an org does not
        collide with itself on a no-op rename.

        Args:
            session: Active database session
            slug: Candidate slug
            exclude_org_id: Organization to exclude from the collision check

        Returns:
            True if another organization already uses this slug
        """
        stmt = select(Organization.id).where(Organization.slug == slug, Organization.id != exclude_org_id).limit(1)
        # The tenant guard auto-scopes Organization queries to the caller's
        # tenant, which silently defeats this check's cross-tenant purpose:
        # another tenant's org holding the slug becomes invisible, the check
        # passes, and the write then violates the GLOBAL idx_org_slug unique
        # index (Sentry GILJOAI-BACKEND-R: a first-login user failed 15 times
        # on the default slug). The bypass restores the global read this
        # method's contract has always documented.
        with tenant_isolation_bypass(
            session,
            reason="slug uniqueness is enforced by a global unique index; the collision check must see all tenants",
            models=(Organization,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def refresh_with_members(self, session: AsyncSession, org: Organization) -> None:
        """
        Refresh an organization including its members relationship.

        Args:
            session: Active database session
            org: Organization ORM instance to refresh
        """
        await session.refresh(org, ["members"])

    async def rollback(self, session: AsyncSession) -> None:
        """
        Rollback the current transaction.

        Args:
            session: Active database session
        """
        await session.rollback()

    # ========================================================================
    # Membership operations
    # ========================================================================

    async def get_membership(
        self,
        session: AsyncSession,
        org_id: str,
        user_id: str,
        tenant_key: str | None = None,
    ) -> OrgMembership | None:
        """
        Get an active membership for a user in an organization.

        Args:
            session: Active database session
            org_id: Organization UUID
            user_id: User UUID
            tenant_key: Tenant isolation key (should always be provided)

        Returns:
            OrgMembership ORM instance or None
        """
        conditions = [
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user_id,
            OrgMembership.is_active,
        ]
        if tenant_key is not None:
            conditions.append(OrgMembership.tenant_key == tenant_key)
        stmt = select(OrgMembership).where(*conditions)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_membership(self, session: AsyncSession, membership: OrgMembership) -> None:
        """
        Add an organization membership to the session.

        Args:
            session: Active database session
            membership: Fully constructed OrgMembership ORM instance
        """
        session.add(membership)

    async def delete_membership(self, session: AsyncSession, membership: OrgMembership) -> None:
        """
        Delete an organization membership.

        Args:
            session: Active database session
            membership: OrgMembership ORM instance to delete
        """
        await session.delete(membership)

    async def list_members(
        self, session: AsyncSession, org_id: str, tenant_key: str | None = None
    ) -> list[OrgMembership]:
        """
        List all active members of an organization.

        Args:
            session: Active database session
            org_id: Organization UUID
            tenant_key: Tenant isolation key (should always be provided)

        Returns:
            List of OrgMembership ORM instances
        """
        conditions = [
            OrgMembership.org_id == org_id,
            OrgMembership.is_active,
        ]
        if tenant_key is not None:
            conditions.append(OrgMembership.tenant_key == tenant_key)
        stmt = select(OrgMembership).where(*conditions).order_by(OrgMembership.joined_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_organizations(
        self, session: AsyncSession, user_id: str, tenant_key: str | None = None
    ) -> list[Organization]:
        """
        Get all organizations a user is a member of (active only).

        Args:
            session: Active database session
            user_id: User UUID
            tenant_key: Tenant isolation key (should always be provided)

        Returns:
            List of Organization ORM instances
        """
        conditions = [
            OrgMembership.user_id == user_id,
            OrgMembership.is_active,
            Organization.is_active,
        ]
        if tenant_key is not None:
            conditions.append(OrgMembership.tenant_key == tenant_key)
        stmt = (
            select(Organization)
            .join(OrgMembership, Organization.id == OrgMembership.org_id)
            .where(*conditions)
            .options(selectinload(Organization.members))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
