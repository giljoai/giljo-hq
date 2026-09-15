# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.auth import APIKey, MCPSession, User
from giljo_mcp.models.config import SetupState
from giljo_mcp.models.organizations import Organization, OrgMembership


logger = logging.getLogger(__name__)


class AuthRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def get_user_by_username(self, session: AsyncSession, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        with tenant_isolation_bypass(
            session,
            reason="login username lookup resolves tenant before authentication",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, session: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        with tenant_isolation_bypass(
            session,
            reason="login email lookup resolves tenant before authentication",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_username_or_email(self, session: AsyncSession, identifier: str) -> User | None:
        user = await self.get_user_by_username(session, identifier)
        if user is None:
            user = await self.get_user_by_email(session, identifier)
        return user

    async def get_user_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id)
        with tenant_isolation_bypass(
            session,
            reason="last-login update resolves authenticated user by global id",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_last_login(self, session: AsyncSession, user: User, timestamp: datetime) -> None:
        user.last_login = timestamp
        await session.flush()

    async def get_total_user_count(self, session: AsyncSession) -> int:
        stmt = select(func.count(User.id))
        with tenant_isolation_bypass(
            session,
            reason="first-admin guard counts users across tenants",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar() or 0


    async def get_setup_state(self, session: AsyncSession, tenant_key: str) -> SetupState | None:
        session.info["tenant_key"] = tenant_key
        stmt = select(SetupState).where(SetupState.tenant_key == tenant_key)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_setup_state(self, session: AsyncSession, setup_state: SetupState) -> None:
        session.add(setup_state)


    async def list_api_keys(
        self,
        session: AsyncSession,
        user_id: str,
        tenant_key: str,
        include_revoked: bool = False,
    ) -> list[APIKey]:
        if include_revoked:
            stmt = (
                select(APIKey)
                .where(APIKey.tenant_key == tenant_key, APIKey.user_id == user_id)
                .order_by(APIKey.created_at.desc())
            )
        else:
            stmt = (
                select(APIKey)
                .where(APIKey.tenant_key == tenant_key, APIKey.user_id == user_id, APIKey.is_active)
                .order_by(APIKey.created_at.desc())
            )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def connected_harnesses(self, session: AsyncSession, tenant_key: str) -> dict[str, str]:
        from giljo_mcp.harness_resolver import harness_from_client_info

        stmt = select(MCPSession.session_data, MCPSession.last_accessed).where(MCPSession.tenant_key == tenant_key)
        result = await session.execute(stmt)
        seen: dict[str, str] = {}
        for session_data, last_accessed in result.all():
            client_info = (session_data or {}).get("client_info") or {}
            harness = harness_from_client_info(client_info.get("name"), client_info.get("version"))
            stamp = last_accessed.isoformat() if last_accessed else ""
            if stamp > seen.get(harness, ""):
                seen[harness] = stamp
        return seen

    async def has_valid_api_key(self, session: AsyncSession, tenant_key: str) -> bool:
        stmt = (
            select(APIKey.id)
            .where(
                APIKey.tenant_key == tenant_key,
                APIKey.is_active.is_(True),
                or_(APIKey.expires_at.is_(None), APIKey.expires_at > datetime.now(UTC)),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_api_key(self, session: AsyncSession, api_key: APIKey) -> APIKey:
        session.add(api_key)
        await session.flush()
        await session.refresh(api_key)
        return api_key

    async def get_api_key_by_id_and_user(
        self, session: AsyncSession, key_id: str, user_id: str, tenant_key: str
    ) -> APIKey | None:
        stmt = select(APIKey).where(APIKey.tenant_key == tenant_key, APIKey.id == key_id, APIKey.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_api_key(
        self,
        session: AsyncSession,
        api_key: APIKey,
        revoked_at: datetime,
    ) -> None:
        api_key.is_active = False
        api_key.revoked_at = revoked_at
        await session.flush()

    async def list_expiring_api_keys(
        self,
        session: AsyncSession,
        tenant_key: str,
        now: datetime,
        cutoff: datetime,
    ) -> list[APIKey]:
        stmt = (
            select(APIKey)
            .where(
                APIKey.tenant_key == tenant_key,
                APIKey.is_active.is_(True),
                APIKey.revoked_at.is_(None),
                APIKey.expires_at.isnot(None),
                APIKey.expires_at > now,
                APIKey.expires_at <= cutoff,
            )
            .order_by(APIKey.expires_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


    async def check_username_exists(self, session: AsyncSession, username: str) -> bool:
        stmt = select(User).where(User.username == username)
        with tenant_isolation_bypass(
            session,
            reason="global username uniqueness check before user creation",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def check_email_exists(self, session: AsyncSession, email: str) -> bool:
        stmt = select(User).where(User.email == email)
        with tenant_isolation_bypass(
            session,
            reason="global email uniqueness check before user creation",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_user(self, session: AsyncSession, user: User) -> User:
        session.add(user)
        await session.flush()
        return user


    async def create_organization(self, session: AsyncSession, org: Organization) -> Organization:
        session.add(org)
        await session.flush()
        return org

    async def create_org_membership(self, session: AsyncSession, membership: OrgMembership) -> None:
        session.add(membership)

    async def get_user_with_org(self, session: AsyncSession, user_id: str) -> User | None:
        from sqlalchemy.orm import selectinload

        stmt = select(User).where(User.id == user_id).options(selectinload(User.organization))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_org_membership(self, session: AsyncSession, org_id: str, user_id: str) -> OrgMembership | None:
        stmt = select(OrgMembership).where(OrgMembership.org_id == org_id).where(OrgMembership.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
