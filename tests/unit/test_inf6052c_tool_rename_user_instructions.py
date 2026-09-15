# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from api.startup.background_tasks import TOOL_RENAME_NOTICE_PAIRS
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_refresh import refresh_tenant_template_instructions
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
)
from tests.helpers.product_crew_helper import seed_crew


_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]*")

_OLD_NAMES = [pair.split("\u2192")[0].strip() for pair in TOOL_RENAME_NOTICE_PAIRS]
_NEW_NAMES = [_IDENTIFIER_RE.findall(pair.split("\u2192")[1])[0] for pair in TOOL_RENAME_NOTICE_PAIRS]

_DEFAULT_TEMPLATE_NAMES = {t["name"] for t in _get_default_templates_v103()}




class TestSeederProduceNewNames:

    def test_no_old_names_in_default_templates(self):
        templates = _get_default_templates_v103()
        for template in templates:
            ui = template.get("user_instructions", "")
            for old in _OLD_NAMES:
                assert old not in ui, (
                    f"Old tool name '{old}' still present in template "
                    f"'{template['name']}' user_instructions — rename incomplete"
                )

    def test_orchestrator_has_new_mission_name(self):
        templates = _get_default_templates_v103()
        orch = next(t for t in templates if t["role"] == "orchestrator")
        assert "get_job_mission" in orch["user_instructions"]

    def test_orchestrator_has_new_context_name(self):
        templates = _get_default_templates_v103()
        orch = next(t for t in templates if t["role"] == "orchestrator")
        assert "get_context" in orch["user_instructions"]
        assert "fetch_context" not in orch["user_instructions"]

    def test_orchestrator_has_new_closeout_name(self):
        templates = _get_default_templates_v103()
        orch = next(t for t in templates if t["role"] == "orchestrator")
        assert "write_project_closeout" in orch["user_instructions"]
        assert "close_project_and_update_memory" not in orch["user_instructions"]




@pytest_asyncio.fixture
async def seeded_tenant(db_session: AsyncSession):
    tenant_key = f"refresh_test_{uuid4().hex[:8]}"
    from giljo_mcp.models.organizations import Organization

    org = Organization(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"Org {tenant_key}",
        slug=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()

    await seed_crew(db_session, tenant_key)
    return tenant_key


@pytest_asyncio.fixture
async def tenant_with_stale_user_instructions(db_session: AsyncSession):
    tenant_key = f"stale_test_{uuid4().hex[:8]}"
    from giljo_mcp.models.organizations import Organization

    org = Organization(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"Org {tenant_key}",
        slug=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()

    await seed_crew(db_session, tenant_key)

    with tenant_session_context(db_session, tenant_key):
        from sqlalchemy import select

        result = await db_session.execute(select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
        templates = result.scalars().all()
        for t in templates:
            if t.name in _DEFAULT_TEMPLATE_NAMES:
                t.user_instructions = (
                    "Call get_agent_mission(job_id) first. "
                    "Then fetch_context for details. "
                    "Finally close_project_and_update_memory()."
                )
        await db_session.commit()

    return tenant_key


@pytest.mark.asyncio
async def test_refresh_rewrites_user_instructions_for_default_templates(
    db_session: AsyncSession, tenant_with_stale_user_instructions
):
    tenant_key = tenant_with_stale_user_instructions
    report = await refresh_tenant_template_instructions(db_session, tenant_key, force=True)
    assert report.user_instructions_rewritten > 0

    with tenant_session_context(db_session, tenant_key):
        from sqlalchemy import select

        result = await db_session.execute(select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
        templates = result.scalars().all()

    for t in templates:
        if t.name in _DEFAULT_TEMPLATE_NAMES:
            for old in _OLD_NAMES:
                assert old not in t.user_instructions, (
                    f"Old tool name '{old}' still in template '{t.name}' after refresh"
                )


@pytest.mark.asyncio
async def test_refresh_leaves_customised_template_untouched(db_session: AsyncSession, seeded_tenant):
    tenant_key = seeded_tenant
    custom_name = "my_custom_agent"
    custom_instructions = "Call get_agent_mission and fetch_context here — USER CUSTOMISED, do not touch."

    custom = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=custom_name,
        category="role",
        role="custom",
        cli_tool="claude",
        background_color="#000000",
        description="Custom agent",
        system_instructions="",
        user_instructions=custom_instructions,
        model="sonnet",
        tools=None,
        variables=[],
        behavioral_rules=[],
        success_criteria=[],
        tool="claude",
        version="1.0.0",
        is_active=True,
        is_default=False,
        tags=["custom"],
    )
    with tenant_session_context(db_session, tenant_key):
        db_session.add(custom)
        await db_session.commit()

    await refresh_tenant_template_instructions(db_session, tenant_key)

    with tenant_session_context(db_session, tenant_key):
        from sqlalchemy import select

        result = await db_session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == custom_name,
            )
        )
        reloaded = result.scalar_one()

    assert reloaded.user_instructions == custom_instructions


@pytest.mark.asyncio
async def test_refresh_default_templates_match_seeder_source(
    db_session: AsyncSession, tenant_with_stale_user_instructions
):
    tenant_key = tenant_with_stale_user_instructions
    await refresh_tenant_template_instructions(db_session, tenant_key, force=True)

    expected_by_name = {t["name"]: t["user_instructions"] for t in _get_default_templates_v103()}

    with tenant_session_context(db_session, tenant_key):
        from sqlalchemy import select

        result = await db_session.execute(select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
        templates = result.scalars().all()

    for t in templates:
        if t.name in expected_by_name:
            expected_fragment = expected_by_name[t.name][:100]
            assert expected_fragment in t.user_instructions, (
                f"Template '{t.name}': refreshed user_instructions does not start with the seeder-defined prose"
            )




class TestBootNoticeBannerContent:

    def _get_banner_body(self) -> str:
        return "; ".join(TOOL_RENAME_NOTICE_PAIRS)

    def test_all_old_names_appear_in_banner_source(self):
        src = self._get_banner_body()
        for old in _OLD_NAMES:
            assert old in src, f"Old name '{old}' missing from boot notice banner source"

    def test_all_new_names_appear_in_banner_source(self):
        src = self._get_banner_body()
        for new in _NEW_NAMES:
            assert new in src, f"New name '{new}' missing from boot notice banner source"

    @pytest.mark.asyncio
    async def test_banner_body_lists_eight_pairs(self, monkeypatch, db_manager, db_session, patched_service_banner):
        from datetime import UTC, datetime
        from uuid import uuid4

        import bcrypt

        from api.startup.background_tasks import _emit_tool_rename_notice_banner
        from giljo_mcp.models.auth import User
        from giljo_mcp.models.organizations import Organization
        from giljo_mcp.services.notification_service import NotificationService

        unique_id = uuid4().hex[:8]
        tenant_key = f"banner_body_{unique_id}"
        org = Organization(
            id=str(uuid4()),
            tenant_key=tenant_key,
            name=f"Org {unique_id}",
            slug=f"org-{unique_id}",
            is_active=True,
        )
        db_session.add(org)
        await db_session.commit()

        svc = NotificationService()
        await _emit_tool_rename_notice_banner(svc, tenant_key, boot_count=1)

        user_id = str(uuid4())
        user = User(
            id=user_id,
            username=f"banner_user_{unique_id}",
            email=f"banner_user_{unique_id}@example.com",
            full_name="Banner User",
            password_hash=bcrypt.hashpw(b"Test1234!", bcrypt.gensalt()).decode("utf-8"),
            role="admin",
            tenant_key=tenant_key,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db_session.add(user)
        await db_session.commit()

        rows = await svc.list_for_user(tenant_key, user_id, surface="banner")
        notice = [r for r in rows if r.type == "system.tool_rename_notice"]
        assert len(notice) == 1, "Expected exactly one tool_rename_notice banner"

        body = notice[0].body
        for old in _OLD_NAMES:
            assert old in body, f"Old name '{old}' missing from banner body"
        for new in _NEW_NAMES:
            assert new in body, f"New name '{new}' missing from banner body"

    @pytest.mark.asyncio
    async def test_banner_suppressed_in_saas(self, monkeypatch):
        from api.startup.background_tasks import (
            _TOOL_RENAME_NOTICE_DEDUPE_KEY,
            _emit_tool_rename_notice_banner,
        )

        resolved = []
        upserted = []

        class _FakeService:
            async def resolve_by_dedupe_key(self, tk, key):
                resolved.append(key)

            async def upsert_by_dedupe_key(self, **kwargs):
                upserted.append(kwargs)

        await _emit_tool_rename_notice_banner(_FakeService(), "any_tenant", boot_count=None)
        assert len(upserted) == 0, "SaaS (boot_count=None) must not upsert the banner"
        assert _TOOL_RENAME_NOTICE_DEDUPE_KEY in resolved, "SaaS path must resolve/dismiss the banner"


@pytest_asyncio.fixture
def patched_service_banner(monkeypatch, db_manager, db_session):
    from giljo_mcp.services.notification_service import NotificationService

    real_init = NotificationService.__init__

    def _init(self, *, db_manager=db_manager, websocket_manager=None, session=db_session):
        real_init(self, db_manager=db_manager, websocket_manager=websocket_manager, session=db_session)

    monkeypatch.setattr(NotificationService, "__init__", _init)
