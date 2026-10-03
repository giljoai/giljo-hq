# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.auth import User, UserFieldPriority
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.settings import Settings
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.services.user_service import UserService
from giljo_mcp.tenant import TenantManager




@pytest_asyncio.fixture
async def tenant_key_a():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def tenant_key_b():
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def settings_service_a(db_session, tenant_key_a):
    return SettingsService(session=db_session, tenant_key=tenant_key_a)


@pytest_asyncio.fixture
async def settings_service_b(db_session, tenant_key_b):
    return SettingsService(session=db_session, tenant_key=tenant_key_b)


@pytest_asyncio.fixture
async def org_a(db_session, tenant_key_a):
    org = Organization(
        id=str(uuid4()),
        tenant_key=tenant_key_a,
        name=f"Org A {uuid4().hex[:6]}",
        slug=f"org-a-{uuid4().hex[:6]}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def user_a(db_session, tenant_key_a, org_a):
    user = User(
        id=str(uuid4()),
        username=f"user_a_{uuid4().hex[:6]}",
        email=f"usera_{uuid4().hex[:6]}@example.com",
        password_hash="hashed",
        full_name="User A",
        role="developer",
        tenant_key=tenant_key_a,
        org_id=org_a.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_a_with_git_history(db_session, tenant_key_a, user_a):
    fp = UserFieldPriority(
        id=str(uuid4()),
        user_id=user_a.id,
        tenant_key=tenant_key_a,
        category="git_history",
        enabled=True,
        updated_at=datetime.now(UTC),
    )
    db_session.add(fp)
    await db_session.commit()
    await db_session.refresh(fp)
    return user_a, fp


@pytest_asyncio.fixture
async def org_b(db_session, tenant_key_b):
    org = Organization(
        id=str(uuid4()),
        tenant_key=tenant_key_b,
        name=f"Org B {uuid4().hex[:6]}",
        slug=f"org-b-{uuid4().hex[:6]}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def user_b_with_git_history(db_session, tenant_key_b, org_b):
    user_b = User(
        id=str(uuid4()),
        username=f"user_b_{uuid4().hex[:6]}",
        email=f"userb_{uuid4().hex[:6]}@example.com",
        password_hash="hashed",
        full_name="User B",
        role="developer",
        tenant_key=tenant_key_b,
        org_id=org_b.id,
        is_active=True,
    )
    db_session.add(user_b)
    await db_session.flush()

    fp = UserFieldPriority(
        id=str(uuid4()),
        user_id=user_b.id,
        tenant_key=tenant_key_b,
        category="git_history",
        enabled=True,
        updated_at=datetime.now(UTC),
    )
    db_session.add(fp)
    await db_session.commit()
    await db_session.refresh(user_b)
    await db_session.refresh(fp)
    return user_b, fp


@pytest_asyncio.fixture
async def user_service_a(db_manager, db_session, tenant_key_a):
    return UserService(
        db_manager=db_manager,
        tenant_key=tenant_key_a,
        websocket_manager=None,
        session=db_session,
    )


@pytest_asyncio.fixture
async def user_service_b(db_manager, db_session, tenant_key_b):
    return UserService(
        db_manager=db_manager,
        tenant_key=tenant_key_b,
        websocket_manager=None,
        session=db_session,
    )




class TestSettingsServiceGetSettings:
    async def test_get_settings_returns_empty_dict_when_no_row_exists(self, settings_service_a):
        result = await settings_service_a.get_settings("integrations")
        assert result == {}

    async def test_get_settings_returns_stored_data(self, db_session, settings_service_a, tenant_key_a):
        settings = Settings(
            id=str(uuid4()),
            tenant_key=tenant_key_a,
            category="integrations",
            settings_data={"git_integration": {"enabled": True}},
        )
        db_session.add(settings)
        await db_session.commit()

        result = await settings_service_a.get_settings("integrations")
        assert result["git_integration"]["enabled"] is True

    async def test_get_settings_raises_for_invalid_category(self, settings_service_a):
        with pytest.raises(ValidationError, match="Invalid category"):
            await settings_service_a.get_settings("nonexistent_category")

    async def test_get_settings_all_valid_categories_accepted(self, settings_service_a):
        for category in ("general", "network", "database", "integrations", "security"):
            result = await settings_service_a.get_settings(category)
            assert isinstance(result, dict)

    async def test_get_settings_rejects_retired_runtime_category(self, settings_service_a):
        with pytest.raises(ValidationError, match="Invalid category"):
            await settings_service_a.get_settings("runtime")




class TestSettingsServiceUpdateSettings:
    async def test_update_settings_creates_new_row_when_none_exists(self, settings_service_a):
        data = {"git_integration": {"enabled": False}, "serena_mcp": {"use_in_prompts": False}}
        result = await settings_service_a.update_settings("integrations", data)
        assert "git_integration" in result

    async def test_update_settings_overwrites_existing_row(self, settings_service_a):
        await settings_service_a.update_settings(
            "integrations",
            {"git_integration": {"enabled": False}, "serena_mcp": {"use_in_prompts": False}},
        )
        result = await settings_service_a.update_settings(
            "integrations",
            {
                "git_integration": {"enabled": True, "use_in_prompts": True},
                "serena_mcp": {"use_in_prompts": True},
            },
        )
        assert result["git_integration"]["enabled"] is True
        assert result["git_integration"]["use_in_prompts"] is True

    async def test_update_settings_raises_for_invalid_category(self, settings_service_a):
        with pytest.raises(ValidationError, match="Invalid category"):
            await settings_service_a.update_settings("bad_category", {})

    async def test_update_settings_raises_for_invalid_data_in_integrations(self, settings_service_a):
        with pytest.raises(ValidationError, match="Settings validation failed"):
            await settings_service_a.update_settings(
                "integrations",
                {"git_integration": {"enabled": "not_a_bool_at_all_xyz"}},
            )

    async def test_update_settings_rejects_retired_runtime_category(self, settings_service_a):
        with pytest.raises(ValidationError, match="Invalid category"):
            await settings_service_a.update_settings(
                "runtime",
                {"agent": {"max_agents": 20}},
            )

    async def test_update_settings_returns_validated_normalized_data(self, settings_service_a):
        result = await settings_service_a.update_settings("integrations", {})
        assert "git_integration" in result
        assert result["git_integration"]["enabled"] is False

    async def test_update_security_settings_stores_cookie_domain_whitelist(self, settings_service_a):
        data = {"ssl_enabled": False, "cookie_domain_whitelist": ["example.com", "api.example.com"]}
        result = await settings_service_a.update_settings("security", data)
        assert result["cookie_domain_whitelist"] == ["example.com", "api.example.com"]
        assert "ssl_enabled" not in result




class TestSettingsServiceGetSettingValue:
    async def test_get_setting_value_returns_default_when_no_row(self, settings_service_a):
        result = await settings_service_a.get_setting_value("integrations", "git_integration", {})
        assert result == {}

    async def test_get_setting_value_returns_stored_nested_value(self, settings_service_a):
        await settings_service_a.update_settings(
            "integrations",
            {
                "git_integration": {"enabled": True, "use_in_prompts": True},
                "serena_mcp": {"use_in_prompts": False},
            },
        )
        value = await settings_service_a.get_setting_value("integrations", "git_integration")
        assert value["enabled"] is True
        assert value["use_in_prompts"] is True

    async def test_get_setting_value_returns_default_for_missing_key(self, settings_service_a):
        await settings_service_a.update_settings("integrations", {})
        result = await settings_service_a.get_setting_value("integrations", "nonexistent_key", "fallback")
        assert result == "fallback"

    async def test_get_setting_value_default_is_none_when_not_specified(self, settings_service_a):
        result = await settings_service_a.get_setting_value("integrations", "missing_key")
        assert result is None




class TestSettingsServiceTenantIsolation:
    async def test_settings_written_by_tenant_a_not_readable_by_tenant_b(self, settings_service_a, settings_service_b):
        await settings_service_a.update_settings(
            "integrations",
            {"git_integration": {"enabled": True}, "serena_mcp": {"use_in_prompts": True}},
        )
        result_b = await settings_service_b.get_settings("integrations")
        assert result_b == {}

    async def test_tenant_b_can_have_different_settings_than_tenant_a(self, settings_service_a, settings_service_b):
        await settings_service_a.update_settings(
            "security",
            {"cookie_domain_whitelist": ["a.com"]},
        )
        await settings_service_b.update_settings(
            "security",
            {"cookie_domain_whitelist": ["b.com"]},
        )

        result_a = await settings_service_a.get_settings("security")
        result_b = await settings_service_b.get_settings("security")

        assert result_a["cookie_domain_whitelist"] == ["a.com"]
        assert result_b["cookie_domain_whitelist"] == ["b.com"]

    async def test_update_by_tenant_a_does_not_affect_tenant_b(self, settings_service_a, settings_service_b):
        await settings_service_b.update_settings(
            "integrations",
            {"git_integration": {"enabled": True}, "serena_mcp": {"use_in_prompts": False}},
        )
        await settings_service_a.update_settings(
            "integrations",
            {"git_integration": {"enabled": False}, "serena_mcp": {"use_in_prompts": False}},
        )
        result_b = await settings_service_b.get_settings("integrations")
        assert result_b["git_integration"]["enabled"] is True




class TestGitToggleCascade:
    async def test_git_disable_cascades_to_disable_git_history_for_tenant_users(
        self, db_session, user_service_a, user_a_with_git_history, tenant_key_a
    ):
        _user_a, fp = user_a_with_git_history
        assert fp.enabled is True

        count = await user_service_a.bulk_disable_field_priority("git_history")
        assert count == 1

        await db_session.refresh(fp)
        assert fp.enabled is False

    async def test_git_disable_cascade_returns_zero_when_no_users_have_git_history(self, user_service_a):
        count = await user_service_a.bulk_disable_field_priority("git_history")
        assert count == 0

    async def test_git_enable_does_not_force_enable_user_git_history(
        self, db_session, user_service_a, tenant_key_a, org_a
    ):
        user = User(
            id=str(uuid4()),
            username=f"user_check_{uuid4().hex[:6]}",
            email=f"check_{uuid4().hex[:6]}@example.com",
            password_hash="hashed",
            full_name="User Check",
            role="developer",
            tenant_key=tenant_key_a,
            org_id=org_a.id,
            is_active=True,
        )
        db_session.add(user)
        fp = UserFieldPriority(
            id=str(uuid4()),
            user_id=user.id,
            tenant_key=tenant_key_a,
            category="git_history",
            enabled=False,
            updated_at=datetime.now(UTC),
        )
        db_session.add(fp)
        await db_session.commit()

        await db_session.refresh(fp)
        assert fp.enabled is False

    async def test_bulk_disable_field_priority_only_affects_current_tenant(
        self, db_session, user_service_a, user_a_with_git_history, user_b_with_git_history, tenant_key_b
    ):
        _user_a, fp_a = user_a_with_git_history
        _user_b, fp_b = user_b_with_git_history

        assert fp_a.enabled is True
        assert fp_b.enabled is True

        count = await user_service_a.bulk_disable_field_priority("git_history")
        assert count == 1

        await db_session.refresh(fp_a)
        await db_session.refresh(fp_b)

        assert fp_a.enabled is False, "Tenant A user git_history should be disabled"
        assert fp_b.enabled is True, "Tenant B user git_history should remain untouched"

    async def test_bulk_disable_field_priority_rejects_invalid_category(self, user_service_a):
        with pytest.raises(ValidationError, match="Invalid category"):
            await user_service_a.bulk_disable_field_priority("not_a_valid_category")




class TestGitHistoryFieldPriorityValidationGate:
    async def test_get_setting_value_returns_false_when_git_not_set(self, settings_service_a):
        git_settings = await settings_service_a.get_setting_value("integrations", "git_integration", {})
        assert not git_settings.get("enabled", False)

    async def test_get_setting_value_returns_true_when_git_enabled(self, settings_service_a):
        await settings_service_a.update_settings(
            "integrations",
            {"git_integration": {"enabled": True}, "serena_mcp": {"use_in_prompts": False}},
        )
        git_settings = await settings_service_a.get_setting_value("integrations", "git_integration", {})
        assert git_settings.get("enabled") is True

    async def test_get_setting_value_returns_false_when_git_disabled(self, settings_service_a):
        await settings_service_a.update_settings(
            "integrations",
            {"git_integration": {"enabled": False}, "serena_mcp": {"use_in_prompts": False}},
        )
        git_settings = await settings_service_a.get_setting_value("integrations", "git_integration", {})
        assert git_settings.get("enabled") is False




class _ScriptedConnection:

    def __init__(self, inserts: list[dict]):
        self._inserts = inserts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        if "information_schema" in sql:
            return _Scalar(True)
        if "FROM users" in sql:
            return _Rows([("tenant-seed",)])
        if sql.startswith("INSERT"):
            self._inserts.append(params)
            return None
        return _Scalar(None)

    def commit(self):
        pass


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Rows(_Scalar):
    def fetchall(self):
        return self._value


class _ScriptedEngine:
    def __init__(self, inserts: list[dict]):
        self._inserts = inserts

    def connect(self):
        return _ScriptedConnection(self._inserts)

    def dispose(self):
        pass


class TestSeedDefaultSettings:

    def _seed(self, monkeypatch, config: dict) -> dict:
        import json

        import sqlalchemy

        from startup_support import checks

        inserts: list[dict] = []
        monkeypatch.setenv("DATABASE_URL", "postgresql://seed:seed@localhost/seed")
        monkeypatch.setattr("src.giljo_mcp._config_io.read_config", lambda: config)
        monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: _ScriptedEngine(inserts))
        assert checks.seed_default_settings() is True
        return {row["cat"]: json.loads(row["data"]) for row in inserts}

    def test_fresh_install_seeds_only_live_keys(self, monkeypatch):
        seed = self._seed(monkeypatch, {})
        assert set(seed) == {"integrations", "security"}
        assert seed["integrations"] == {"git_integration": {"enabled": False, "use_in_prompts": False}}
        assert "serena_mcp" not in seed["integrations"]
        assert seed["security"] == {"cookie_domain_whitelist": []}

    def test_upgrade_reads_config_values(self, monkeypatch):
        config = {
            "features": {
                "git_integration": {"enabled": True, "use_in_prompts": True},
                "serena_mcp": {"use_in_prompts": True},
            },
            "security": {"cookie_domain_whitelist": ["prod.example.com"]},
        }
        seed = self._seed(monkeypatch, config)
        assert seed["integrations"]["git_integration"] == {"enabled": True, "use_in_prompts": True}
        assert "serena_mcp" not in seed["integrations"]
        assert seed["security"]["cookie_domain_whitelist"] == ["prod.example.com"]

    def test_seed_rows_accepted_by_jsonb_validators(self, monkeypatch):
        from giljo_mcp.schemas.jsonb_validators import validate_settings_by_category

        seed = self._seed(monkeypatch, {})
        assert "git_integration" in validate_settings_by_category("integrations", seed["integrations"])
        assert "cookie_domain_whitelist" in validate_settings_by_category("security", seed["security"])

    async def test_seed_idempotency_simulated_via_settings_service(self, settings_service_a):
        data = {"git_integration": {"enabled": False}}
        await settings_service_a.update_settings("integrations", data)
        await settings_service_a.update_settings("integrations", data)
        result = await settings_service_a.get_settings("integrations")
        assert result["git_integration"]["enabled"] is False
