# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
)
from tests.helpers.product_crew_helper import make_product, seed_crew


pytestmark = pytest.mark.asyncio

EXPECTED_SEEDED_ROLES = {"analyzer", "implementer", "tester", "reviewer", "documenter"}


async def _rows_for(session: AsyncSession, tenant_key: str) -> list[AgentTemplate]:
    with tenant_session_context(session, tenant_key):
        result = await session.execute(
            select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key).order_by(AgentTemplate.role)
        )
        return list(result.scalars().all())


async def test_a_new_product_gets_exact_default_rows(db_session: AsyncSession, test_tenant_key: str) -> None:
    product, names = await seed_crew(db_session, test_tenant_key)

    assert len(names) == len(EXPECTED_SEEDED_ROLES)

    rows = await _rows_for(db_session, test_tenant_key)
    assert {row.role for row in rows} == EXPECTED_SEEDED_ROLES
    assert SYSTEM_MANAGED_ROLES.isdisjoint({row.role for row in rows})

    for row in rows:
        assert row.category == "role"
        assert row.is_active is True
        assert row.product_id == product.id
        assert row.is_default is False
        assert row.tags == ["default", "product"]


async def test_seeded_text_is_byte_identical_to_seed_definition(db_session: AsyncSession, test_tenant_key: str) -> None:
    await seed_crew(db_session, test_tenant_key)

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
    product, names = await seed_crew(db_session, test_tenant_key)
    assert len(names) == len(EXPECTED_SEEDED_ROLES)
    _same, again = await seed_crew(db_session, test_tenant_key, product)
    assert again == []

    rows = await _rows_for(db_session, test_tenant_key)
    assert len(rows) == len(EXPECTED_SEEDED_ROLES)


async def test_a_second_product_is_seeded_too(db_session: AsyncSession, test_tenant_key: str) -> None:
    _first, first_names = await seed_crew(db_session, test_tenant_key)
    second = await make_product(db_session, test_tenant_key, name="Second product")
    _second, second_names = await seed_crew(db_session, test_tenant_key, second)

    assert len(second_names) == len(EXPECTED_SEEDED_ROLES)
    assert set(first_names).isdisjoint(second_names), "names stay unique per ACCOUNT (ruling 5)"

    rows = await _rows_for(db_session, test_tenant_key)
    second_rows = [r for r in rows if r.product_id == second.id]
    assert {r.role for r in second_rows} == EXPECTED_SEEDED_ROLES
    bootstrap = _get_mcp_bootstrap_section()
    by_role = {t["role"]: t for t in _get_default_templates_v103()}
    for row in second_rows:
        assert row.user_instructions == _seeded_user_instructions(by_role[row.role])
        assert row.system_instructions == bootstrap


async def test_orchestrator_identity_is_composed_without_a_database_row(
    db_session: AsyncSession, test_tenant_key: str
) -> None:
    await seed_crew(db_session, test_tenant_key)

    rows = await _rows_for(db_session, test_tenant_key)
    assert not [row for row in rows if row.role == "orchestrator"]

    identity = compose_orchestrator_identity(None, tool="claude-code")
    assert "## Three-Phase Workflow" in identity
    assert "### RESPONDING TO CONTEXT REQUESTS" in identity
    assert "## ORCHESTRATOR COORDINATION PRINCIPLES" in identity
    assert "## MCP Tool Usage" in identity
    assert "## CHECK-IN PROTOCOL" in identity
