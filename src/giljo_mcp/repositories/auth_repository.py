# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
AuthRepository - Data access layer for authentication-related entities.

BE-5022c: Extracted from auth_service.py to enforce the service->repository
boundary. All database reads and writes for User (auth context), APIKey,
SetupState, Organization (creation during registration), and OrgMembership
(creation during registration) are routed through this repository.

Tenant isolation is enforced at the query level where applicable.
Auth operations (login) intentionally omit tenant_key filters because
the user's tenant is unknown until after authentication succeeds.
"""

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
    """
    Repository for authentication-related database operations.

    Methods accept an AsyncSession parameter (session-in pattern) so the
    calling service controls transaction boundaries.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ========================================================================
    # User lookups (auth context -- no tenant_key filter for login)
    # ========================================================================

    async def get_user_by_username(self, session: AsyncSession, username: str) -> User | None:
        """
        Get user by username (cross-tenant, used for login).

        Args:
            session: Active database session
            username: Username to look up

        Returns:
            User ORM instance or None
        """
        stmt = select(User).where(User.username == username)
        with tenant_isolation_bypass(
            session,
            reason="login username lookup resolves tenant before authentication",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, session: AsyncSession, email: str) -> User | None:
        """
        Get user by email (cross-tenant, used for login).

        Case-insensitive lookup. Email has a global UNIQUE constraint
        (``User.email`` column, ``src/giljo_mcp/models/auth.py``), so at most
        one user matches for a given email across all tenants. Mirrors the
        ``get_user_by_username`` login-boundary pattern (see module docstring):
        no tenant_key filter because the tenant is unknown until after
        authentication succeeds.

        Part of AUTH-EMAIL dual-lookup (handover af53e62b,
        ``internal design notes``).

        Args:
            session: Active database session
            email: Email address to look up (case-insensitive)

        Returns:
            User ORM instance or None
        """
        stmt = select(User).where(func.lower(User.email) == email.lower())
        with tenant_isolation_bypass(
            session,
            reason="login email lookup resolves tenant before authentication",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_username_or_email(self, session: AsyncSession, identifier: str) -> User | None:
        """
        Resolve a user by username OR email (dual-lookup).

        Mirrors the Phase 1 login-boundary pattern shipped in
        ``AuthService.authenticate_user`` (commit 42842d18, handover
        af53e62b): username lookup runs first; on miss, a case-insensitive
        email lookup is attempted. Same cross-tenant semantics as the
        component helpers (see module docstring): tenant_key is intentionally
        omitted because the tenant is unknown at the login boundary, and
        ``User.email`` + ``User.username`` carry global UNIQUE constraints.

        Used by PIN recovery and first-login endpoints so that users can
        supply either identifier on the wire. Phase 4 (AUTH-EMAIL).

        Args:
            session: Active database session
            identifier: Username or email address

        Returns:
            User ORM instance or None
        """
        user = await self.get_user_by_username(session, identifier)
        if user is None:
            user = await self.get_user_by_email(session, identifier)
        return user

    async def get_user_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        """
        Get user by ID (cross-tenant, used for last-login updates).

        Args:
            session: Active database session
            user_id: User UUID

        Returns:
            User ORM instance or None
        """
        stmt = select(User).where(User.id == user_id)
        with tenant_isolation_bypass(
            session,
            reason="last-login update resolves authenticated user by global id",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_last_login(self, session: AsyncSession, user: User, timestamp: datetime) -> None:
        """
        Set the last_login timestamp on a user and commit.

        Args:
            session: Active database session
            user: User ORM instance (must be attached to session)
            timestamp: Login timestamp (UTC)
        """
        user.last_login = timestamp
        await session.flush()

    async def get_total_user_count(self, session: AsyncSession) -> int:
        """
        Count all users across all tenants (used for first-admin guard).

        Args:
            session: Active database session

        Returns:
            Total user count
        """
        stmt = select(func.count(User.id))
        with tenant_isolation_bypass(
            session,
            reason="first-admin guard counts users across tenants",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar() or 0

    # ========================================================================
    # SetupState
    # ========================================================================

    async def get_setup_state(self, session: AsyncSession, tenant_key: str) -> SetupState | None:
        """
        Get setup state for a tenant.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation

        Returns:
            SetupState ORM instance or None
        """
        session.info["tenant_key"] = tenant_key
        stmt = select(SetupState).where(SetupState.tenant_key == tenant_key)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_setup_state(self, session: AsyncSession, setup_state: SetupState) -> None:
        """
        Add a new SetupState record to the session.

        Args:
            session: Active database session
            setup_state: Fully constructed SetupState ORM instance
        """
        session.add(setup_state)

    # ========================================================================
    # API Key operations
    # ========================================================================

    async def list_api_keys(
        self,
        session: AsyncSession,
        user_id: str,
        tenant_key: str,
        include_revoked: bool = False,
    ) -> list[APIKey]:
        """
        List API keys for a user, ordered by created_at descending.

        Args:
            session: Active database session
            user_id: User UUID
            include_revoked: Include revoked (inactive) keys

        Returns:
            List of APIKey ORM instances
        """
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
        """Map harness token -> ISO timestamp of its most recent connect (FE-9500).

        Derived on the fly from EXISTING ``mcp_sessions`` rows -- the same
        no-new-table idiom as :meth:`has_valid_api_key` / FE-9274. Every MCP
        client records its ``initialize`` clientInfo in ``session_data``; that is
        the only place the server learns WHICH tool attached, and it is what makes
        a per-tool Connect status honest instead of painting one workspace-wide
        credential flag onto every tool card.

        Tenant-scoped (ADR-009). Rows whose clientInfo is absent or unrecognized
        resolve to ``generic`` -- reported honestly rather than guessed at, and
        callers must render that as "something connected, harness unknown".
        """
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
        """True if the tenant has >=1 active, non-expired API key (FE-9274 connect-status).

        Tenant-scoped (not user-scoped) -- ADR-009 makes this equivalent to
        "this user's key is live" (tenant_key is per-user, permanently), but
        matches the credential-status contract's tenant-scoped definition.
        """
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
        """
        Persist a new API key, commit, and refresh.

        Args:
            session: Active database session
            api_key: Fully constructed APIKey ORM instance

        Returns:
            Refreshed APIKey instance
        """
        session.add(api_key)
        await session.flush()
        await session.refresh(api_key)
        return api_key

    async def get_api_key_by_id_and_user(
        self, session: AsyncSession, key_id: str, user_id: str, tenant_key: str
    ) -> APIKey | None:
        """
        Get an API key by ID scoped to a user.

        Args:
            session: Active database session
            key_id: API key UUID
            user_id: User UUID (ownership check)

        Returns:
            APIKey ORM instance or None
        """
        stmt = select(APIKey).where(APIKey.tenant_key == tenant_key, APIKey.id == key_id, APIKey.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_api_key(
        self,
        session: AsyncSession,
        api_key: APIKey,
        revoked_at: datetime,
    ) -> None:
        """
        Mark an API key as revoked and commit.

        Args:
            session: Active database session
            api_key: APIKey ORM instance to revoke
            revoked_at: Revocation timestamp (UTC)
        """
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
        """List active, non-revoked API keys expiring within (now, cutoff].

        Tenant-scoped. Excludes keys without an ``expires_at`` (never expire),
        already-expired keys (``expires_at <= now``), and revoked/inactive keys.

        Args:
            session: Active database session.
            tenant_key: Tenant to scan.
            now: Lower bound (exclusive) — already-expired keys are skipped.
            cutoff: Upper bound (inclusive) — ``now + days_ahead``.

        Returns:
            List of APIKey ORM instances expiring in the window.
        """
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

    # ========================================================================
    # User registration (write helpers)
    # ========================================================================

    async def check_username_exists(self, session: AsyncSession, username: str) -> bool:
        """
        Check if a username is already taken (global scope).

        Args:
            session: Active database session
            username: Username to check

        Returns:
            True if username exists
        """
        stmt = select(User).where(User.username == username)
        with tenant_isolation_bypass(
            session,
            reason="global username uniqueness check before user creation",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def check_email_exists(self, session: AsyncSession, email: str) -> bool:
        """
        Check if an email is already taken (global scope).

        Args:
            session: Active database session
            email: Email to check

        Returns:
            True if email exists
        """
        stmt = select(User).where(User.email == email)
        with tenant_isolation_bypass(
            session,
            reason="global email uniqueness check before user creation",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_user(self, session: AsyncSession, user: User) -> User:
        """
        Add a user to the session and flush (to obtain user.id).

        Does NOT commit -- the caller manages transaction boundaries
        (e.g., to also create memberships in the same transaction).

        Args:
            session: Active database session
            user: Fully constructed User ORM instance

        Returns:
            User instance with generated id
        """
        session.add(user)
        await session.flush()
        return user

    # ========================================================================
    # Organization & Membership helpers (used during registration)
    # ========================================================================

    async def create_organization(self, session: AsyncSession, org: Organization) -> Organization:
        """
        Add an organization and flush (to obtain org.id).

        Args:
            session: Active database session
            org: Fully constructed Organization ORM instance

        Returns:
            Organization with generated id
        """
        session.add(org)
        await session.flush()
        return org

    async def create_org_membership(self, session: AsyncSession, membership: OrgMembership) -> None:
        """
        Add an organization membership to the session.

        Args:
            session: Active database session
            membership: Fully constructed OrgMembership ORM instance
        """
        session.add(membership)

    async def get_user_with_org(self, session: AsyncSession, user_id: str) -> User | None:
        """
        Get user with eagerly loaded organization relationship.

        Args:
            session: Active database session
            user_id: User UUID

        Returns:
            User ORM instance with organization loaded, or None
        """
        from sqlalchemy.orm import selectinload

        stmt = select(User).where(User.id == user_id).options(selectinload(User.organization))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_org_membership(self, session: AsyncSession, org_id: str, user_id: str) -> OrgMembership | None:
        """
        Get a specific organization membership.

        Args:
            session: Active database session
            org_id: Organization UUID
            user_id: User UUID

        Returns:
            OrgMembership ORM instance or None
        """
        stmt = select(OrgMembership).where(OrgMembership.org_id == org_id).where(OrgMembership.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
