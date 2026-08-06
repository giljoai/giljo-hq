# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9360: pin the live template seeding path against the dead-code removal.

BE-9360 deletes ``UnifiedTemplateManager.get_template()``, the uncalled
``installer/core/config.py:seed_default_orchestrator_template()``, and the
discarded ``UnifiedTemplateManager()`` construction at ``template_seeder.py:112``.
None of those sit on a live path -- but the third one is *lexically inside*
``_seed_tenant_templates``, so the seeding flow is the one place where a
mistake would be silent and expensive. This module pins it at the layer it
lives (the seeder), on a real database, so the removal cannot change what a
fresh tenant receives.

Four acceptance invariants ride on the assertions below:

* **I1 fresh CE install seeding** -- ``POST /api/auth/register``
  (``api/endpoints/auth/registration.py:256``) calls ``seed_tenant_templates``;
  the installer seeds no templates at all. ``test_fresh_tenant_gets_exact_default_rows``
  pins the resulting row set.
* **I2 restore-to-default / heal migrations** -- ``template_refresh`` and the
  ``ce_0049`` / ``ce_0084`` heals key on the seeded text matching the seed
  definition BYTE FOR BYTE; a whitespace-level drift makes a heal silently
  match zero rows. ``test_seeded_text_is_byte_identical_to_seed_definition``
  pins that contract.
* **I3 giljo_setup export** reads these same rows back out of the database, so
  the row set pinned here is its input.
* **I4 job/workorder identity** -- workers resolve a DB row (pinned here);
  orchestrators resolve no row at all and are composed in code, which
  ``test_orchestrator_identity_is_composed_without_a_database_row`` pins.

Project: BE-9360.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_bootstrap_section,
    _seeded_user_instructions,
    compose_orchestrator_identity,
    seed_tenant_templates,
)


pytestmark = pytest.mark.asyncio

# The five roles a fresh tenant receives. "orchestrator" is deliberately absent:
# it is system-managed, so no row is ever created for it (BE-9333).
EXPECTED_SEEDED_ROLES = {"analyzer", "implementer", "tester", "reviewer", "documenter"}


async def _rows_for(session: AsyncSession, tenant_key: str) -> list[AgentTemplate]:
    """Read the tenant's rows back under explicit tenant context (tenant guard)."""
    with tenant_session_context(session, tenant_key):
        result = await session.execute(
            select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key).order_by(AgentTemplate.role)
        )
        return list(result.scalars().all())


async def test_fresh_tenant_gets_exact_default_rows(db_session: AsyncSession, test_tenant_key: str) -> None:
    """I1: a fresh tenant receives exactly the five default worker rows."""
    seeded_count = await seed_tenant_templates(db_session, test_tenant_key)

    assert seeded_count == len(EXPECTED_SEEDED_ROLES)

    rows = await _rows_for(db_session, test_tenant_key)
    assert {row.role for row in rows} == EXPECTED_SEEDED_ROLES
    # The system-managed orchestrator must NOT acquire a row -- its identity is
    # composed at read time, and a row here would shadow that composition.
    assert SYSTEM_MANAGED_ROLES.isdisjoint({row.role for row in rows})

    for row in rows:
        assert row.category == "role"
        assert row.is_active is True
        assert row.is_default is True
        assert row.product_id is None
        assert row.tags == ["default", "tenant"]


async def test_seeded_text_is_byte_identical_to_seed_definition(db_session: AsyncSession, test_tenant_key: str) -> None:
    """I2: seeded text matches the seed definition byte for byte.

    ``refresh_tenant_template_instructions`` and the ``ce_0049`` / ``ce_0084``
    heal migrations decide whether a row is "provably unedited" by comparing it
    to this exact text. Any drift -- a stripped newline, a re-wrapped line --
    makes every heal match zero rows and silently do nothing.
    """
    await seed_tenant_templates(db_session, test_tenant_key)

    rows = {row.role: row for row in await _rows_for(db_session, test_tenant_key)}
    bootstrap = _get_mcp_bootstrap_section()

    for template_def in _get_default_templates_v103():
        role = template_def["role"]
        if role in SYSTEM_MANAGED_ROLES:
            continue
        row = rows[role]
        assert row.user_instructions == _seeded_user_instructions(template_def)
        assert row.system_instructions == bootstrap
        assert row.description == template_def["description"]
        assert row.version == template_def["version"]


async def test_seeding_is_idempotent(db_session: AsyncSession, test_tenant_key: str) -> None:
    """The CE installer reruns on every boot; a second seed must be a no-op."""
    assert await seed_tenant_templates(db_session, test_tenant_key) == len(EXPECTED_SEEDED_ROLES)
    assert await seed_tenant_templates(db_session, test_tenant_key) == 0

    rows = await _rows_for(db_session, test_tenant_key)
    assert len(rows) == len(EXPECTED_SEEDED_ROLES)


async def test_orchestrator_identity_is_composed_without_a_database_row(
    db_session: AsyncSession, test_tenant_key: str
) -> None:
    """I4: the orchestrator's identity comes from the code seed, not a row.

    ``mission_service`` and ``mission_orchestration_builders`` both call
    ``compose_orchestrator_identity``; nothing reads an orchestrator template
    row, because none exists.
    """
    await seed_tenant_templates(db_session, test_tenant_key)

    rows = await _rows_for(db_session, test_tenant_key)
    assert not [row for row in rows if row.role == "orchestrator"]

    identity = compose_orchestrator_identity(None, tool="claude-code")
    assert "## Three-Phase Workflow" in identity
    assert "### RESPONDING TO CONTEXT REQUESTS" in identity
    assert "## ORCHESTRATOR COORDINATION PRINCIPLES" in identity
    # The harness half is appended unconditionally, after the seed body.
    assert "## MCP Tool Usage" in identity
    assert "## CHECK-IN PROTOCOL" in identity
