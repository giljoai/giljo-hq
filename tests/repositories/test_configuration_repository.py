# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    return ConfigurationRepository(db_manager)


@pytest_asyncio.fixture
async def test_configurations(db_session, test_tenant_key):
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




class TestTenantConfigurationDomain:

    @pytest.mark.asyncio
    async def test_list_tenant_keys(
        self, config_repo, db_session, test_tenant_key, test_configurations, other_tenant_configurations
    ):
        tenant_keys = await config_repo.list_tenant_keys(db_session)

        assert len(tenant_keys) >= 2
        assert test_tenant_key in tenant_keys
        assert "other_tenant" in tenant_keys

    @pytest.mark.asyncio
    async def test_list_tenant_keys_empty(self, config_repo, db_session):
        tenant_keys = await config_repo.list_tenant_keys(db_session)

        assert isinstance(tenant_keys, list)




class TestSetupDomain:

    @pytest.mark.asyncio
    async def test_check_admin_user_exists_true(self, config_repo, db_session, admin_user):
        exists = await config_repo.check_admin_user_exists(db_session)

        assert exists is True

    @pytest.mark.asyncio
    async def test_check_admin_user_exists_false(self, config_repo, db_manager):
        async with db_manager.get_session_async() as fresh_session:
            from sqlalchemy import delete

            from giljo_mcp.models.auth import User

            with tenant_isolation_bypass(
                fresh_session,
                reason="test setup removes admin users across tenants",
                models=(User,),
            ):
                await fresh_session.execute(delete(User).where(User.role == "admin"))
            await fresh_session.commit()

            exists = await config_repo.check_admin_user_exists(fresh_session)

            assert exists is False




class TestHealthCheckDomain:

    @pytest.mark.asyncio
    async def test_execute_health_check_success(self, config_repo, db_session):
        is_healthy = await config_repo.execute_health_check(db_session)

        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_execute_health_check_failure(self, config_repo, db_manager, monkeypatch):

        class FailingSession:
            async def execute(self, stmt):
                raise RuntimeError("Database connection failed")

        is_healthy = await config_repo.execute_health_check(FailingSession())

        assert is_healthy is False




class TestPerTenantValueDomain:

    @pytest.mark.asyncio
    async def test_get_value_returns_none_when_unset(self, config_repo, db_session, test_tenant_key):
        result = await config_repo.get_value(db_session, test_tenant_key, "agent_silence_threshold_minutes")

        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_value_then_get_value_round_trips(self, config_repo, db_session, test_tenant_key):
        await config_repo.upsert_value(
            db_session, test_tenant_key, "agent_silence_threshold_minutes", 25, category="system"
        )
        await db_session.commit()

        result = await config_repo.get_value(db_session, test_tenant_key, "agent_silence_threshold_minutes")

        assert result == 25

    @pytest.mark.asyncio
    async def test_upsert_value_overwrites_existing_row_no_duplicate(self, config_repo, db_session, test_tenant_key):
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
        other_tenant_key = "other_silence_tenant"
        await config_repo.upsert_value(
            db_session, test_tenant_key, "agent_silence_threshold_minutes", 25, category="system"
        )
        await db_session.commit()

        result = await config_repo.get_value(db_session, other_tenant_key, "agent_silence_threshold_minutes")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_values_for_key_loads_every_tenant_in_one_query(self, config_repo, db_session):
        tenant_a = "silence_tenant_a"
        tenant_b = "silence_tenant_b"
        await config_repo.upsert_value(db_session, tenant_a, "agent_silence_threshold_minutes", 5, category="system")
        await config_repo.upsert_value(db_session, tenant_b, "agent_silence_threshold_minutes", 90, category="system")
        await config_repo.upsert_value(db_session, tenant_a, "unrelated_key", "ignored", category="general")
        await db_session.commit()

        overrides = await config_repo.get_all_values_for_key(db_session, "agent_silence_threshold_minutes")

        assert overrides[tenant_a] == 5
        assert overrides[tenant_b] == 90
        assert "unrelated_key" not in overrides.values()
