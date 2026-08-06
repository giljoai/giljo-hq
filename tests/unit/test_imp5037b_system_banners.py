# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for the CE admin system-banner emitters (IMP-5037b Phase 1, item D).

Covers emit_system_banners end-to-end against the DB:
- pending-migrations banner upsert + resolve
- update-available banner upsert + resolve
- skills-drift banner upsert
- admin-only visibility (role_filter='admin')
- tenants without admins are skipped

Parallel-safe: TransactionalTestContext (db_session) + no module globals.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio

from api.startup import background_tasks
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.notification_service import NotificationService


@pytest_asyncio.fixture
async def tenant_key(db_session):
    unique_id = str(uuid4())[:8]
    org = Organization(
        id=str(uuid4()),
        tenant_key=f"banner_tenant_{unique_id}",
        name=f"Org {unique_id}",
        slug=f"org-{unique_id}",
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()
    return org.tenant_key


async def _make_user(db_session, tenant_key: str, role: str) -> str:
    unique_id = str(uuid4())[:8]
    user = User(
        id=str(uuid4()),
        username=f"buser_{unique_id}",
        email=f"buser_{unique_id}@example.com",
        full_name="Banner User",
        password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
        role=role,
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


def _fake_state(db_manager, db_session, *, update_available=None):
    """A minimal APIState-like object whose db_manager shares the test session.

    background_tasks.emit_system_banners builds its own NotificationService from
    state.db_manager. To keep everything inside the test transaction, we patch
    NotificationService to always use the shared db_session (below).
    """
    return SimpleNamespace(
        db_manager=db_manager,
        websocket_manager=None,
        update_available=update_available,
        pending_migration=False,
    )


@pytest_asyncio.fixture
def patched_service(monkeypatch, db_manager, db_session):
    """Force every NotificationService built inside emit_system_banners to share
    the test transaction's session, and stub the cross-tenant admin scan to the
    test session as well."""
    real_init = NotificationService.__init__

    def _init(self, *, db_manager=db_manager, websocket_manager=None, session=db_session):
        real_init(self, db_manager=db_manager, websocket_manager=websocket_manager, session=db_session)

    monkeypatch.setattr(NotificationService, "__init__", _init)


async def _admins_via_session(db_session, monkeypatch):
    from sqlalchemy import select

    async def _scan(_db_manager):
        result = await db_session.execute(
            select(User.tenant_key).distinct().where(User.role == "admin", User.is_active.is_(True))
        )
        return {row[0] for row in result.fetchall()}

    monkeypatch.setattr(background_tasks, "_tenant_keys_with_admins", _scan)


class TestPendingMigrationsBanner:
    @pytest.mark.asyncio
    async def test_upsert_then_resolve(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)

        monkeypatch.setattr(
            background_tasks, "get_pending_migration_info", lambda state: {"pending": 2, "head": "ce_0040"}
        )
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

        state = _fake_state(db_manager, db_session)
        await background_tasks.emit_system_banners(state)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        migration_rows = [r for r in rows if r.type == "system.pending_migrations"]
        assert len(migration_rows) == 1
        assert migration_rows[0].role_filter == "admin"
        assert migration_rows[0].dismissible is False
        assert migration_rows[0].cta_route == "Tools"
        assert migration_rows[0].payload["pending"] == 2

        # Now migrations applied -> resolve
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)
        await background_tasks.emit_system_banners(state)
        rows_after = await service.list_for_user(tenant_key, admin_id, surface="banner")
        assert [r for r in rows_after if r.type == "system.pending_migrations"] == []

    @pytest.mark.asyncio
    async def test_hidden_from_non_admin(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        dev_id = await _make_user(db_session, tenant_key, "developer")
        await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)

        monkeypatch.setattr(
            background_tasks, "get_pending_migration_info", lambda state: {"pending": 1, "head": "ce_0040"}
        )
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

        await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

        service = NotificationService()
        dev_rows = await service.list_for_user(tenant_key, dev_id, surface="banner")
        assert [r for r in dev_rows if r.type == "system.pending_migrations"] == []


class TestUpdateAvailableBanner:
    @pytest.mark.asyncio
    async def test_upsert_then_resolve(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

        state = _fake_state(
            db_manager,
            db_session,
            update_available={"commits_behind": 4, "message": "4 updates available"},
        )
        await background_tasks.emit_system_banners(state)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        update_rows = [r for r in rows if r.type == "system.update_available"]
        assert len(update_rows) == 1
        assert update_rows[0].payload["commits_behind"] == 4

        # FE-6020: the update-available banner links OUT to GitHub releases, not an
        # in-app route. It must carry no cta_route and a usable release_url in the
        # payload (git-mode installs supply no URL → fall back to the releases page).
        assert update_rows[0].cta_route is None
        assert update_rows[0].payload["release_url"] == "https://github.com/giljoai/giljo-hq/releases"
        # FE-6020: copy no longer tells users to run the (migration-only) update.py.
        assert "update.py" not in update_rows[0].title

        state.update_available = None
        await background_tasks.emit_system_banners(state)
        rows_after = await service.list_for_user(tenant_key, admin_id, surface="banner")
        assert [r for r in rows_after if r.type == "system.update_available"] == []


class TestSkillsDriftBanner:
    @pytest.mark.asyncio
    async def test_upsert(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)

        async def _drift(_db_manager, _tenant_key):
            return {"current": "2.0.0", "announced": "1.0.0", "message": "drift msg"}

        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _drift)

        await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        drift_rows = [r for r in rows if r.type == "system.skills_drift"]
        assert len(drift_rows) == 1
        assert drift_rows[0].dedupe_key == "system.skills_drift"
        assert drift_rows[0].payload["current"] == "2.0.0"


async def _none_async(_db_manager, _tenant_key=None):
    return None


async def _drift_async(_db_manager, _tenant_key=None):
    return {"current": "2.0.0", "announced": "1.0.0", "message": "drift msg"}


class TestSaaSBannerSuppression:
    """BE-6031c: under GILJO_MODE=saas, suppress update_available + pending_migrations
    banners, but KEEP skills_drift. CE (mode unset / 'ce') emits all three."""

    @pytest.mark.asyncio
    async def test_saas_suppresses_update_and_migrations_keeps_drift(
        self, monkeypatch, db_manager, db_session, tenant_key, patched_service
    ):
        monkeypatch.setenv("GILJO_MODE", "saas")
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)

        monkeypatch.setattr(
            background_tasks, "get_pending_migration_info", lambda state: {"pending": 3, "head": "ce_0040"}
        )
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _drift_async)

        state = _fake_state(
            db_manager,
            db_session,
            update_available={"commits_behind": 4, "message": "4 updates available"},
        )
        await background_tasks.emit_system_banners(state)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        types = {r.type for r in rows}
        assert "system.update_available" not in types
        assert "system.pending_migrations" not in types
        assert "system.skills_drift" in types

    @pytest.mark.asyncio
    async def test_ce_emits_all_three(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        monkeypatch.delenv("GILJO_MODE", raising=False)
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)

        monkeypatch.setattr(
            background_tasks, "get_pending_migration_info", lambda state: {"pending": 3, "head": "ce_0040"}
        )
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _drift_async)

        state = _fake_state(
            db_manager,
            db_session,
            update_available={"commits_behind": 4, "message": "4 updates available"},
        )
        await background_tasks.emit_system_banners(state)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        types = {r.type for r in rows}
        assert "system.update_available" in types
        assert "system.pending_migrations" in types
        assert "system.skills_drift" in types

    @pytest.mark.asyncio
    async def test_ce_mode_explicit_emits_all_three(
        self, monkeypatch, db_manager, db_session, tenant_key, patched_service
    ):
        monkeypatch.setenv("GILJO_MODE", "ce")
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)

        monkeypatch.setattr(
            background_tasks, "get_pending_migration_info", lambda state: {"pending": 1, "head": "ce_0040"}
        )
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _drift_async)

        state = _fake_state(
            db_manager,
            db_session,
            update_available={"commits_behind": 2, "message": "2 updates available"},
        )
        await background_tasks.emit_system_banners(state)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        types = {r.type for r in rows}
        assert "system.update_available" in types
        assert "system.pending_migrations" in types
        assert "system.skills_drift" in types


class TestContextTuningDueBanner:
    """FE-9202: the 14-day context-tuning-due reminder emitted via emit_system_banners.

    The compute gate (product age + activity + preference) is unit-tested against
    context_tuning_banner directly in test_fe9202_context_tuning_banner.py; here we
    lock the emit/resolve wiring and the banner's distinguishing shape (per-user,
    NOT admin-only).
    """

    @staticmethod
    def _patch_quiet(monkeypatch):
        """Silence the other banner families so only the tuning banner is under test."""
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

    @pytest.mark.asyncio
    async def test_upsert_then_resolve(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        user_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        self._patch_quiet(monkeypatch)

        async def _due(_db_manager, _tenant_key):
            return {"product_id": "prod-1", "product_name": "Acme", "projects_since_tune": 3}

        monkeypatch.setattr(background_tasks, "compute_context_tuning_due", _due)

        state = _fake_state(db_manager, db_session)
        await background_tasks.emit_system_banners(state)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, user_id, surface="banner")
        tuning = [r for r in rows if r.type == "system.context_tuning_due"]
        assert len(tuning) == 1
        assert tuning[0].role_filter is None  # per-user, NOT admin-gated
        assert tuning[0].dismissible is True
        assert tuning[0].cta_route == "Tools"
        assert tuning[0].dedupe_key == "system.context_tuning_due"
        assert tuning[0].payload["projects_since_tune"] == 3
        assert "Acme" in tuning[0].body

        # No longer due -> the open row resolves (auto-clear).
        async def _not_due(_db_manager, _tenant_key):
            return None

        monkeypatch.setattr(background_tasks, "compute_context_tuning_due", _not_due)
        await background_tasks.emit_system_banners(state)
        rows_after = await service.list_for_user(tenant_key, user_id, surface="banner")
        assert [r for r in rows_after if r.type == "system.context_tuning_due"] == []

    @pytest.mark.asyncio
    async def test_visible_to_non_admin(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        # role_filter=None -> a non-admin user sees it (unlike the admin system banners).
        dev_id = await _make_user(db_session, tenant_key, "developer")
        await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        self._patch_quiet(monkeypatch)

        async def _due(_db_manager, _tenant_key):
            return {"product_id": "prod-1", "product_name": "Acme", "projects_since_tune": 1}

        monkeypatch.setattr(background_tasks, "compute_context_tuning_due", _due)

        await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

        service = NotificationService()
        dev_rows = await service.list_for_user(tenant_key, dev_id, surface="banner")
        assert [r for r in dev_rows if r.type == "system.context_tuning_due"]  # present for the developer


class TestPerTenantIsolation:
    """FE-9202 F1: one tenant raising must not abort the emit for the others."""

    @pytest.mark.asyncio
    async def test_one_tenant_raises_others_still_emit(
        self, monkeypatch, db_manager, db_session, tenant_key, patched_service
    ):
        # Two tenants: the FIRST one's tuning compute raises; the SECOND must
        # still receive its skills-drift banner.
        good_key = tenant_key
        bad_key = f"{tenant_key}_bad"
        good_admin = await _make_user(db_session, good_key, "admin")

        # Enumerate both tenants in a stable order, the failing one FIRST.
        monkeypatch.setattr(background_tasks, "_tenant_keys_with_admins", lambda _dbm: _ordered_keys(bad_key, good_key))
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)

        async def _drift(_db_manager, tk):
            return {"current": "2.0.0", "announced": "1.0.0", "message": "drift"}

        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _drift)

        async def _tuning(_db_manager, tk):
            if tk == bad_key:
                raise RuntimeError("simulated per-tenant failure")

        monkeypatch.setattr(background_tasks, "compute_context_tuning_due", _tuning)

        await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

        service = NotificationService()
        rows = await service.list_for_user(good_key, good_admin, surface="banner")
        assert [r for r in rows if r.type == "system.skills_drift"], "good tenant lost its banner to a sibling failure"


async def _ordered_keys(*keys):
    """Deterministic ordered tenant list (failing tenant first) for the isolation test."""
    return list(keys)


class TestSaaSUpdateCheckerSuppression:
    """BE-6031c: start_update_checker is a no-op under saas, before any git/network work."""

    @pytest.mark.asyncio
    async def test_saas_returns_none_without_touching_git(self, monkeypatch):
        from api.startup import update_checker

        monkeypatch.setenv("GILJO_MODE", "saas")
        reached = {"git": False}

        async def _record(*_a, **_kw):
            reached["git"] = True
            return True

        monkeypatch.setattr(update_checker, "_is_git_repo", _record)
        monkeypatch.setattr(update_checker, "_has_remote", _record)

        result = await update_checker.start_update_checker(SimpleNamespace())
        assert result is None
        assert reached["git"] is False

    @pytest.mark.asyncio
    async def test_ce_reaches_git_layer(self, monkeypatch):
        from api.startup import update_checker

        monkeypatch.delenv("GILJO_MODE", raising=False)
        reached = {"git": False}

        async def _is_git(*_a, **_kw):
            reached["git"] = True
            return False

        async def _no_remote(*_a, **_kw):
            return False

        monkeypatch.setattr(update_checker, "_is_git_repo", _is_git)
        monkeypatch.setattr(update_checker, "_has_remote", _no_remote)
        monkeypatch.setattr(update_checker, "_HAS_PACKAGING", False)

        result = await update_checker.start_update_checker(SimpleNamespace())
        assert reached["git"] is True
        assert result is None


class TestToolRenameNoticeBanner:
    """INF-6049a: the first-3-boots CE tool-rename migration notice."""

    async def _emit_with_count(self, monkeypatch, db_manager, db_session, count):
        """Drive emit_system_banners with the boot count pinned and the other CE
        banners quiet."""
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

        async def _count(_db_manager):
            return count

        monkeypatch.setattr(background_tasks, "_get_tool_rename_boot_count", _count)
        await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("count", [1, 2, 3])
    async def test_fires_on_boots_1_to_3(self, monkeypatch, db_manager, db_session, tenant_key, patched_service, count):
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        await self._emit_with_count(monkeypatch, db_manager, db_session, count)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        notice = [r for r in rows if r.type == "system.tool_rename_notice"]
        assert len(notice) == 1, f"expected the tool-rename notice on boot {count}"
        assert notice[0].role_filter == "admin"
        assert notice[0].dismissible is True
        assert notice[0].cta_route == "Tools"
        # INF-6052c: banner body now lists all 8 renames; spot-check two representative pairs
        assert "get_agent_mission" in notice[0].body
        assert "get_job_mission" in notice[0].body
        assert "get_context" in notice[0].body
        assert "giljo_setup" in notice[0].body

    @pytest.mark.asyncio
    @pytest.mark.parametrize("count", [0, 4, 5])
    async def test_absent_on_boot_4_plus_or_unset(
        self, monkeypatch, db_manager, db_session, tenant_key, patched_service, count
    ):
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        await self._emit_with_count(monkeypatch, db_manager, db_session, count)

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        assert [r for r in rows if r.type == "system.tool_rename_notice"] == [], (
            f"notice must NOT show at boot count {count}"
        )

    @pytest.mark.asyncio
    async def test_never_emitted_in_saas(self, monkeypatch, db_manager, db_session, tenant_key, patched_service):
        admin_id = await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        monkeypatch.setenv("GILJO_MODE", "saas")
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

        # Even with the counter in-window, SaaS must never show the CE notice.
        async def _count(_db_manager):
            return 1

        monkeypatch.setattr(background_tasks, "_get_tool_rename_boot_count", _count)
        await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

        service = NotificationService()
        rows = await service.list_for_user(tenant_key, admin_id, surface="banner")
        assert [r for r in rows if r.type == "system.tool_rename_notice"] == []


class TestToolRenameBootCounter:
    """INF-6049a: the global boot counter is bumped once per startup, not per tick."""

    async def _reset_counter(self, db_session) -> None:
        """Delete any pre-existing counter row so each test starts from zero.

        system_settings is a non-tenant global table; its rows persist across
        test runs when a previous test committed (or when the DB was seeded).
        The TransactionalTestContext rolls back writes made IN this test, but
        cannot un-see rows already committed before the transaction opened.
        """
        from sqlalchemy import delete

        from giljo_mcp.models.system_setting import SystemSetting
        from giljo_mcp.services.settings_service import TOOL_RENAME_BOOT_COUNT_KEY

        await db_session.execute(delete(SystemSetting).where(SystemSetting.key == TOOL_RENAME_BOOT_COUNT_KEY))
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_increment_counts_then_saturates(self, db_session):
        from giljo_mcp.services.settings_service import SystemSettingsService

        await self._reset_counter(db_session)
        svc = SystemSettingsService(db_session)
        assert await svc.get_tool_rename_boot_count() == 0  # unset
        assert await svc.increment_tool_rename_boot_count() == 1
        assert await svc.increment_tool_rename_boot_count() == 2
        assert await svc.increment_tool_rename_boot_count() == 3
        assert await svc.increment_tool_rename_boot_count() == 4  # one past the window
        # Saturates — further startups do not grow it unbounded.
        assert await svc.increment_tool_rename_boot_count() == 4
        assert await svc.get_tool_rename_boot_count() == 4

    @pytest.mark.asyncio
    async def test_emit_cycles_do_not_advance_the_counter(
        self, monkeypatch, db_manager, db_session, tenant_key, patched_service
    ):
        """An update-checker tick re-runs emit_system_banners; that must NOT bump
        the boot counter (else 'first 3 boots' silently becomes 'first 3 ticks')."""
        from giljo_mcp.services.settings_service import SystemSettingsService

        await self._reset_counter(db_session)
        await _make_user(db_session, tenant_key, "admin")
        await _admins_via_session(db_session, monkeypatch)
        monkeypatch.setattr(background_tasks, "get_pending_migration_info", lambda state: None)
        monkeypatch.setattr(background_tasks, "_compute_skills_drift", _none_async)

        svc = SystemSettingsService(db_session)
        await svc.increment_tool_rename_boot_count()
        await svc.increment_tool_rename_boot_count()  # count = 2 (two process boots)

        # Make emit read the SHARED test session's counter (real persistence).
        async def _count(_db_manager):
            return await SystemSettingsService(db_session).get_tool_rename_boot_count()

        monkeypatch.setattr(background_tasks, "_get_tool_rename_boot_count", _count)

        # Three emit cycles = a startup plus two update-checker ticks.
        for _ in range(3):
            await background_tasks.emit_system_banners(_fake_state(db_manager, db_session))

        assert await SystemSettingsService(db_session).get_tool_rename_boot_count() == 2
