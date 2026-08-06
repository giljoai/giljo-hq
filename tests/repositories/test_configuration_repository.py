# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for ConfigurationRepository (Handover 1011 Phase 3).

Test-driven development: Comprehensive coverage of all configuration repository methods
with CRITICAL tenant isolation testing.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Configuration
from giljo_mcp.models.auth import User
from giljo_mcp.repositories.configuration_repository import ConfigurationRepository


@pytest.fixture
def config_repo(db_manager):
    """Create ConfigurationRepository instance"""
    return ConfigurationRepository(db_manager)


@pytest_asyncio.fixture
async def test_configurations(db_session, test_tenant_key):
    """Create test configurations for a tenant"""
    configurations = []
    for i in range(3):
        config = Configuration(
            tenant_key=test_tenant_key,
            key=f"test.key.{i}",
            value=f"test_value_{i}",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(config)
        configurations.append(config)
    await db_session.commit()
    return configurations


@pytest_asyncio.fixture
async def other_tenant_configurations(db_session):
    """Create configurations for a different tenant"""
    other_tenant_key = "other_tenant"
    configurations = []
    for i in range(2):
        config = Configuration(
            tenant_key=other_tenant_key,
            key=f"other.key.{i}",
            value=f"other_value_{i}",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(config)
        configurations.append(config)
    await db_session.commit()
    return configurations


@pytest_asyncio.fixture
async def admin_user(db_session):
    """Create an admin user for first-run detection tests"""
    user = User(
        id="admin_001",
        tenant_key="default",
        username="admin",
        email="admin@test.com",
        password_hash="hashed_password",
        role="admin",
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    return user


# ============================================================================
# TENANT CONFIGURATION DOMAIN TESTS
# ============================================================================


class TestTenantConfigurationDomain:
    """Test tenant configuration retrieval and management"""

    @pytest.mark.asyncio
    async def test_list_tenant_keys(
        self, config_repo, db_session, test_tenant_key, test_configurations, other_tenant_configurations
    ):
        """Test listing all tenant keys with configurations"""
        tenant_keys = await config_repo.list_tenant_keys(db_session)

        assert len(tenant_keys) >= 2  # At least our two test tenants
        assert test_tenant_key in tenant_keys  # Use the fixture-provided tenant key
        assert "other_tenant" in tenant_keys

    @pytest.mark.asyncio
    async def test_list_tenant_keys_empty(self, config_repo, db_session):
        """Test listing tenant keys when no configurations exist"""
        tenant_keys = await config_repo.list_tenant_keys(db_session)

        # Should return empty list if no configurations
        assert isinstance(tenant_keys, list)


# ============================================================================
# SETUP / FIRST-RUN DOMAIN TESTS
# ============================================================================


class TestSetupDomain:
    """Test setup and first-run detection"""

    @pytest.mark.asyncio
    async def test_check_admin_user_exists_true(self, config_repo, db_session, admin_user):
        """Test admin user existence check when admin exists"""
        exists = await config_repo.check_admin_user_exists(db_session)

        assert exists is True

    @pytest.mark.asyncio
    async def test_check_admin_user_exists_false(self, config_repo, db_manager):
        """Test admin user existence check when no admin exists"""
        # Create a fresh session with no admin users
        async with db_manager.get_session_async() as fresh_session:
            # First verify no admin exists by not creating one
            from sqlalchemy import delete

            from giljo_mcp.models.auth import User

            # Delete any admin users that might exist from other tests
            with tenant_isolation_bypass(
                fresh_session,
                reason="test setup removes admin users across tenants",
                models=(User,),
            ):
                await fresh_session.execute(delete(User).where(User.role == "admin"))
            await fresh_session.commit()

            # Now check - should be False
            exists = await config_repo.check_admin_user_exists(fresh_session)

            assert exists is False


# ============================================================================
# HEALTH CHECK DOMAIN TESTS
# ============================================================================


class TestHealthCheckDomain:
    """Test database health checks"""

    @pytest.mark.asyncio
    async def test_execute_health_check_success(self, config_repo, db_session):
        """Test successful database health check"""
        is_healthy = await config_repo.execute_health_check(db_session)

        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_execute_health_check_failure(self, config_repo, db_manager, monkeypatch):
        """Test health check when database fails — only RuntimeError/OSError are caught."""

        # Create a mock session that raises RuntimeError (caught by health check)
        class FailingSession:
            async def execute(self, stmt):
                raise RuntimeError("Database connection failed")

        is_healthy = await config_repo.execute_health_check(FailingSession())

        assert is_healthy is False


# ============================================================================
# PER-TENANT VALUE DOMAIN TESTS (FE-9241 — SaaS-configurable silence timer)
# ============================================================================


class TestPerTenantValueDomain:
    """Test get_value / upsert_value / get_all_values_for_key (per-tenant JSONB CRUD)."""

    @pytest.mark.asyncio
    async def test_get_value_returns_none_when_unset(self, config_repo, db_session, test_tenant_key):
        """A tenant with no row for the key gets None (caller falls back to default)."""
        result = await config_repo.get_value(db_session, test_tenant_key, "agent_silence_threshold_minutes")

        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_value_then_get_value_round_trips(self, config_repo, db_session, test_tenant_key):
        """upsert_value writes a row that get_value reads back unchanged."""
        await config_repo.upsert_value(
            db_session, test_tenant_key, "agent_silence_threshold_minutes", 25, category="system"
        )
        await db_session.commit()

        result = await config_repo.get_value(db_session, test_tenant_key, "agent_silence_threshold_minutes")

        assert result == 25

    @pytest.mark.asyncio
    async def test_upsert_value_overwrites_existing_row_no_duplicate(self, config_repo, db_session, test_tenant_key):
        """A second upsert for the same (tenant_key, key) updates in place (ON CONFLICT DO UPDATE),
        never creates a duplicate row — proves the uq_config_tenant_key constraint is exercised."""
        await config_repo.upsert_value(
            db_session, test_tenant_key, "agent_silence_threshold_minutes", 25, category="system"
        )
        await db_session.commit()

        await config_repo.upsert_value(
            db_session, test_tenant_key, "agent_silence_threshold_minutes", 40, category="system"
        )
        await db_session.commit()

        result = await db_session.execute(
            select(Configuration).where(
                Configuration.tenant_key == test_tenant_key,
                Configuration.key == "agent_silence_threshold_minutes",
            )
        )
        rows = result.scalars().all()

        assert len(rows) == 1
        assert rows[0].value == 40

    @pytest.mark.asyncio
    async def test_get_value_is_tenant_isolated(self, config_repo, db_session, test_tenant_key):
        """Tenant A's value is invisible to tenant B (ADR-009)."""
        other_tenant_key = "other_silence_tenant"
        await config_repo.upsert_value(
            db_session, test_tenant_key, "agent_silence_threshold_minutes", 25, category="system"
        )
        await db_session.commit()

        result = await config_repo.get_value(db_session, other_tenant_key, "agent_silence_threshold_minutes")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_values_for_key_loads_every_tenant_in_one_query(self, config_repo, db_session):
        """The cross-tenant batch loader used by the silence detector returns every
        tenant's value for the key in a single query result (no N+1 per-tenant reads)."""
        tenant_a = "silence_tenant_a"
        tenant_b = "silence_tenant_b"
        await config_repo.upsert_value(db_session, tenant_a, "agent_silence_threshold_minutes", 5, category="system")
        await config_repo.upsert_value(db_session, tenant_b, "agent_silence_threshold_minutes", 90, category="system")
        # A different key must NOT be picked up by the loader.
        await config_repo.upsert_value(db_session, tenant_a, "unrelated_key", "ignored", category="general")
        await db_session.commit()

        overrides = await config_repo.get_all_values_for_key(db_session, "agent_silence_threshold_minutes")

        assert overrides[tenant_a] == 5
        assert overrides[tenant_b] == 90
        assert "unrelated_key" not in overrides.values()
