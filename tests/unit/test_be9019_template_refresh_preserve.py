# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.models.templates import TemplateArchive
from giljo_mcp.template_refresh import refresh_tenant_template_instructions
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_bootstrap_section,
    _seeded_user_instructions,
)
from tests.helpers.product_crew_helper import seed_crew


_EDITED_ROLE = "reviewer"
_USER_EDITED_PROSE = "You are OUR reviewer. Follow our house style guide. DO NOT REVERT THIS."


@pytest_asyncio.fixture
async def seeded_tenant(db_session: AsyncSession):
    tenant_key = f"be9019_{uuid4().hex[:8]}"
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


async def _get_by_name(db_session: AsyncSession, tenant_key: str, name: str) -> AgentTemplate:
    with tenant_session_context(db_session, tenant_key):
        result = await db_session.execute(
            select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.name == name,
            )
        )
        return result.scalar_one()


async def _edit_prose(db_session: AsyncSession, tenant_key: str, name: str, prose: str) -> None:
    with tenant_session_context(db_session, tenant_key):
        row = await _get_by_name(db_session, tenant_key, name)
        row.user_instructions = prose
        await db_session.commit()


@pytest.mark.asyncio
async def test_refresh_preserves_user_edited_default_named_prose(db_session: AsyncSession, seeded_tenant):
    tenant_key = seeded_tenant
    await _edit_prose(db_session, tenant_key, _EDITED_ROLE, _USER_EDITED_PROSE)

    report = await refresh_tenant_template_instructions(db_session, tenant_key)

    row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    assert row.user_instructions == _USER_EDITED_PROSE
    assert _EDITED_ROLE in report.skipped_edited
    assert row.system_instructions == _get_mcp_bootstrap_section()


@pytest.mark.asyncio
async def test_refresh_rerenders_provably_unedited_row(db_session: AsyncSession, seeded_tenant):
    tenant_key = seeded_tenant
    default_def = next(t for t in _get_default_templates_v103() if t["name"] == _EDITED_ROLE)
    expected = _seeded_user_instructions(default_def)

    report = await refresh_tenant_template_instructions(db_session, tenant_key)

    row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    assert row.user_instructions == expected
    assert _EDITED_ROLE not in report.skipped_edited
    assert report.user_instructions_rewritten >= 1
    assert report.archived == 0


@pytest.mark.asyncio
async def test_force_overwrites_edited_row_and_archives_it(db_session: AsyncSession, seeded_tenant):
    tenant_key = seeded_tenant
    await _edit_prose(db_session, tenant_key, _EDITED_ROLE, _USER_EDITED_PROSE)

    default_def = next(t for t in _get_default_templates_v103() if t["name"] == _EDITED_ROLE)
    expected = _seeded_user_instructions(default_def)

    edited_row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    template_id = edited_row.id

    report = await refresh_tenant_template_instructions(db_session, tenant_key, force=True)

    row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    assert row.user_instructions == expected
    assert _EDITED_ROLE not in report.skipped_edited
    assert report.archived == 1

    with tenant_session_context(db_session, tenant_key):
        result = await db_session.execute(select(TemplateArchive).where(TemplateArchive.template_id == template_id))
        archives = result.scalars().all()
    assert any(a.user_instructions == _USER_EDITED_PROSE for a in archives), (
        "force overwrite must archive the user's edited prose before reverting"
    )


@pytest.mark.parametrize("role_name", ["implementer", "tester", "documenter"])
@pytest.mark.asyncio
async def test_be9259_neutralized_persona_edits_do_not_clobber_saved_overrides(
    db_session: AsyncSession, seeded_tenant, role_name: str
):
    tenant_key = seeded_tenant
    edited_prose = f"CUSTOM {role_name} prose the user wrote by hand. DO NOT REVERT THIS."
    await _edit_prose(db_session, tenant_key, role_name, edited_prose)

    report = await refresh_tenant_template_instructions(db_session, tenant_key)

    row = await _get_by_name(db_session, tenant_key, role_name)
    assert row.user_instructions == edited_prose, "saved override was clobbered by the persona-neutralization rewrite"
    assert role_name in report.skipped_edited


@pytest.mark.asyncio
async def test_refresh_never_touches_custom_named_row(db_session: AsyncSession, seeded_tenant):
    tenant_key = seeded_tenant
    custom_name = "my_custom_agent"
    custom_prose = "Custom agent prose — refresh must never look at this."

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
        user_instructions=custom_prose,
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

    report = await refresh_tenant_template_instructions(db_session, tenant_key, force=True)

    row = await _get_by_name(db_session, tenant_key, custom_name)
    assert row.user_instructions == custom_prose
    assert custom_name not in report.skipped_edited
