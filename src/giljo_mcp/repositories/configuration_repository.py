# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Configuration repository for database configuration management.

Handover 1011: Migrates configuration queries from api/endpoints/configuration.py
and setup.py to follow the repository pattern with CRITICAL tenant isolation.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import distinct, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Configuration
from giljo_mcp.models.auth import User


class ConfigurationRepository:
    """
    Repository for configuration and setup queries.

    Provides database configuration management with proper tenant isolation.
    All methods MUST include tenant_key parameter where applicable.
    """

    def __init__(self, db_manager):
        """
        Initialize configuration repository.

        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager

    # ============================================================================
    # TENANT CONFIGURATION DOMAIN
    # ============================================================================

    async def list_tenant_keys(
        self,
        session: AsyncSession,
    ) -> list[str]:
        """
        List all distinct tenant keys that have custom configurations.

        Args:
            session: Async database session

        Returns:
            List of tenant keys with configurations
        """
        result = await session.execute(
            select(distinct(Configuration.tenant_key)).where(Configuration.tenant_key.isnot(None))
        )
        return [row[0] for row in result]

    async def get_value(
        self,
        session: AsyncSession,
        tenant_key: str,
        key: str,
    ) -> Any | None:
        """
        Return this tenant's raw JSONB value for a configuration key, or None if unset.

        Args:
            session: Async database session
            tenant_key: Tenant identifier (isolation boundary — ADR-009)
            key: Configuration.key to look up

        Returns:
            The stored JSONB value, or None when the tenant has no row for this key.
        """
        stmt = select(Configuration.value).where(
            Configuration.tenant_key == tenant_key,
            Configuration.key == key,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_value(
        self,
        session: AsyncSession,
        tenant_key: str,
        key: str,
        value: Any,
        category: str = "general",
    ) -> None:
        """
        Upsert a tenant-scoped configuration value (single write path, race-free).

        Uses ``INSERT ... ON CONFLICT (tenant_key, key) DO UPDATE`` (the same
        pattern as ``SystemPromptService._upsert_override``) so two concurrent
        writers for the same (tenant_key, key) resolve via the database
        constraint rather than a select-then-insert-or-update race.

        Args:
            session: Async database session
            tenant_key: Tenant identifier (isolation boundary — ADR-009)
            key: Configuration.key to upsert
            value: JSONB-serializable value to store
            category: Configuration.category (default "general")
        """
        now = datetime.now(UTC)
        stmt = pg_insert(Configuration).values(
            tenant_key=tenant_key,
            project_id=None,
            key=key,
            value=value,
            category=category,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_config_tenant_key",
            set_={"value": stmt.excluded.value, "updated_at": now},
        )
        await session.execute(stmt)

    async def get_all_values_for_key(
        self,
        session: AsyncSession,
        key: str,
    ) -> dict[str, Any]:
        """
        Load EVERY tenant's value for a configuration key in ONE query (cross-tenant).

        For system-wide background jobs (e.g. SilenceDetector) that need every
        tenant's override for a key in a single scan — mirrors
        ``AgentOperationsRepository.find_stale_working_agents``: a legitimate,
        deliberate cross-tenant read for a server-timer job with no per-request
        tenant context, NOT a per-request/user-facing code path.

        No ``tenant_isolation_bypass`` wrapper is needed here: ``Configuration``
        has a nullable ``tenant_key`` (global rows use NULL) and is deliberately
        NOT registered in the enforced tenant-scoped model set — the same reason
        ``list_tenant_keys`` above queries it directly without one.

        Args:
            session: Async database session
            key: Configuration.key to look up across all tenants

        Returns:
            Dict of {tenant_key: value} for every tenant that has a row for this key.
        """
        stmt = select(Configuration.tenant_key, Configuration.value).where(
            Configuration.key == key,
            Configuration.tenant_key.isnot(None),
        )
        result = await session.execute(stmt)
        return dict(result.all())

    # ============================================================================
    # SETUP / FIRST-RUN DOMAIN
    # ============================================================================

    async def check_admin_user_exists(
        self,
        session: AsyncSession,
    ) -> bool:
        """
        Check if at least one admin user exists (for first-run detection).

        Args:
            session: Async database session

        Returns:
            True if admin user exists, False otherwise
        """
        stmt = select(User).where(User.role == "admin").limit(1)
        with tenant_isolation_bypass(
            session,
            reason="setup guard checks for any admin user across tenants",
            models=(User,),
        ):
            result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    # ============================================================================
    # HEALTH CHECK DOMAIN
    # ============================================================================

    async def execute_health_check(
        self,
        session: AsyncSession,
    ) -> bool:
        """
        Execute simple database health check.

        Args:
            session: Async database session

        Returns:
            True if database is responsive, False otherwise
        """
        try:
            await session.execute(text("SELECT 1"))
            return True
        except (RuntimeError, OSError):
            return False
