# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.organizations import Organization, OrgMembership


logger = logging.getLogger(__name__)


class OrgRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def add_organization(self, session: AsyncSession, org: Organization) -> Organization:
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
        stmt = select(Organization).where(Organization.slug == slug)
        if tenant_key is not None:
            stmt = stmt.where(Organization.tenant_key == tenant_key)
        stmt = stmt.options(selectinload(Organization.members))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def slug_taken_by_other_org(self, session: AsyncSession, slug: str, exclude_org_id: str) -> bool:
        stmt = select(Organization.id).where(Organization.slug == slug, Organization.id != exclude_org_id).limit(1)
        with tenant_isolation_bypass(
            session,
            reason="slug uniqueness is enforced by a global unique index; the collision check must see all tenants",
            models=(Organization,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def refresh_with_members(self, session: AsyncSession, org: Organization) -> None:
        await session.refresh(org, ["members"])

    async def rollback(self, session: AsyncSession) -> None:
        await session.rollback()


    async def get_membership(
        self,
        session: AsyncSession,
        org_id: str,
        user_id: str,
        tenant_key: str | None = None,
    ) -> OrgMembership | None:
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
        session.add(membership)

    async def delete_membership(self, session: AsyncSession, membership: OrgMembership) -> None:
        await session.delete(membership)

    async def list_members(
        self, session: AsyncSession, org_id: str, tenant_key: str | None = None
    ) -> list[OrgMembership]:
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
