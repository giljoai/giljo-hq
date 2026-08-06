# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9019: refresh must not silently clobber user-edited default-named templates.

The bug: ``refresh_tenant_template_instructions`` overwrote ``user_instructions``
for every row whose NAME matched a shipped default, silently reverting hand-tuned
prose to shipped text. The docstring claimed the opposite.

The fix (preserve-by-default + force + archive):
- a default-named row whose prose diverges from the shipped default is treated as a
  USER EDIT and left untouched (its name is reported in ``skipped_edited``);
- a provably-unedited default-named row is re-rendered (no-op prose) and its
  rules/criteria reset;
- ``force=True`` overwrites edited rows back to the default, ARCHIVING each first so
  the edit is recoverable;
- ``system_instructions`` (the user-content-free bootstrap) is always refreshed.

DB tests are parallel-safe: TransactionalTestContext (db_session) + no module globals.

Edition Scope: Both (CE + SaaS). The refresh path runs on both editions.
"""

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
    seed_tenant_templates,
)


# A non-orchestrator default role (orchestrator is system-managed and never seeded).
_EDITED_ROLE = "reviewer"
_USER_EDITED_PROSE = "You are OUR reviewer. Follow our house style guide. DO NOT REVERT THIS."


@pytest_asyncio.fixture
async def seeded_tenant(db_session: AsyncSession):
    """Seed a fresh tenant with default templates and return its key."""
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

    await seed_tenant_templates(db_session, tenant_key)
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
    """Divert a default-named row's user_instructions to simulate a user edit."""
    with tenant_session_context(db_session, tenant_key):
        row = await _get_by_name(db_session, tenant_key, name)
        row.user_instructions = prose
        await db_session.commit()


@pytest.mark.asyncio
async def test_refresh_preserves_user_edited_default_named_prose(db_session: AsyncSession, seeded_tenant):
    """The core bug: an EDITED default-named row must survive refresh untouched."""
    tenant_key = seeded_tenant
    await _edit_prose(db_session, tenant_key, _EDITED_ROLE, _USER_EDITED_PROSE)

    report = await refresh_tenant_template_instructions(db_session, tenant_key)

    row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    # Prose preserved — NOT reverted to shipped text.
    assert row.user_instructions == _USER_EDITED_PROSE
    # Reported as skipped-because-edited.
    assert _EDITED_ROLE in report.skipped_edited
    # system_instructions (user-content-free) IS still refreshed.
    assert row.system_instructions == _get_mcp_bootstrap_section()


@pytest.mark.asyncio
async def test_refresh_rerenders_provably_unedited_row(db_session: AsyncSession, seeded_tenant):
    """A pristine (unedited) default-named row is re-rendered and not skipped."""
    tenant_key = seeded_tenant
    default_def = next(t for t in _get_default_templates_v103() if t["name"] == _EDITED_ROLE)
    expected = _seeded_user_instructions(default_def)

    report = await refresh_tenant_template_instructions(db_session, tenant_key)

    row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    assert row.user_instructions == expected
    assert _EDITED_ROLE not in report.skipped_edited
    assert report.user_instructions_rewritten >= 1
    # Unedited rows carry no user edits, so nothing is archived.
    assert report.archived == 0


@pytest.mark.asyncio
async def test_force_overwrites_edited_row_and_archives_it(db_session: AsyncSession, seeded_tenant):
    """force=True reverts an edited row to the default AND archives the edit first."""
    tenant_key = seeded_tenant
    await _edit_prose(db_session, tenant_key, _EDITED_ROLE, _USER_EDITED_PROSE)

    default_def = next(t for t in _get_default_templates_v103() if t["name"] == _EDITED_ROLE)
    expected = _seeded_user_instructions(default_def)

    edited_row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    template_id = edited_row.id

    report = await refresh_tenant_template_instructions(db_session, tenant_key, force=True)

    row = await _get_by_name(db_session, tenant_key, _EDITED_ROLE)
    # Prose reverted to shipped default.
    assert row.user_instructions == expected
    assert _EDITED_ROLE not in report.skipped_edited
    assert report.archived == 1

    # The edit is recoverable — an archive holds the pre-overwrite prose.
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
    """BE-9259 rewrote the implementer/tester/documenter seed prose to strip
    dogfooding contamination (GiljoAI-as-target-product, our pytest/Vitest/
    SaaS/tenant_key toolchain mandated to the customer). That rewrite changes
    the shipped default text for these three roles — this proves the refresh
    path still treats a tenant's saved override as sacrosanct rather than
    silently reverting it to the new neutralized default (fail-first check
    for the exact gap BE-9019 originally fixed, now re-verified against the
    NEW content)."""
    tenant_key = seeded_tenant
    edited_prose = f"CUSTOM {role_name} prose the user wrote by hand. DO NOT REVERT THIS."
    await _edit_prose(db_session, tenant_key, role_name, edited_prose)

    report = await refresh_tenant_template_instructions(db_session, tenant_key)

    row = await _get_by_name(db_session, tenant_key, role_name)
    assert row.user_instructions == edited_prose, "saved override was clobbered by the persona-neutralization rewrite"
    assert role_name in report.skipped_edited


@pytest.mark.asyncio
async def test_refresh_never_touches_custom_named_row(db_session: AsyncSession, seeded_tenant):
    """A custom-NAMED row is out of scope for refresh entirely (edited or not)."""
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

    # force=True to prove even a forced refresh leaves custom-named rows alone.
    report = await refresh_tenant_template_instructions(db_session, tenant_key, force=True)

    row = await _get_by_name(db_session, tenant_key, custom_name)
    assert row.user_instructions == custom_prose
    assert custom_name not in report.skipped_edited
