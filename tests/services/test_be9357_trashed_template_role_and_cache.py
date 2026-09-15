# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.mission_repository import MissionRepository
from giljo_mcp.tenant_guard import tenant_isolation_bypass, tenant_session_context


def _tenant() -> str:
    return f"be9357-{uuid4().hex[:16]}"


def _template(
    tenant_key: str,
    role: str,
    *,
    deleted: bool = False,
    is_default: bool = False,
) -> AgentTemplate:
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"be9357-{role}-{uuid4().hex[:8]}",
        category="role",
        role=role,
        system_instructions="sys",
        user_instructions="user",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        is_default=is_default,
        deleted_at=datetime.now(UTC) if deleted else None,
    )




@pytest.mark.asyncio
async def test_trashed_tenant_template_is_not_resolved_by_role(db_session):
    tenant = _tenant()
    db_session.add(_template(tenant, "implementer", deleted=True))
    await db_session.flush()

    with tenant_session_context(db_session, tenant):
        found = await MissionRepository().get_template_by_role(db_session, tenant, "implementer")

    assert found is None, (
        "get_template_by_role still resolves a soft-deleted template for the role. The "
        "operator deleted the agent precisely because its instructions were wrong, and "
        "role resolution keeps handing those instructions back as a live identity."
    )


@pytest.mark.asyncio
async def test_live_tenant_template_still_resolves_by_role(db_session):
    tenant = _tenant()
    live = _template(tenant, "implementer")
    db_session.add(live)
    await db_session.flush()

    with tenant_session_context(db_session, tenant):
        found = await MissionRepository().get_template_by_role(db_session, tenant, "implementer")

    assert found is not None and found.id == live.id




@pytest.mark.asyncio
async def test_trashed_default_template_is_not_resolved_by_role(db_session):
    tenant = _tenant()
    db_session.add(_template(tenant, "tester", deleted=True, is_default=True))
    await db_session.flush()

    with tenant_session_context(db_session, tenant):
        found = await MissionRepository().get_template_by_role(db_session, tenant, "tester")

    assert found is None, "A trashed is_default template is still resolved for its role."


@pytest.mark.asyncio
async def test_is_default_branch_scopes_to_the_calling_tenant(db_session):
    mine, theirs = _tenant(), _tenant()
    db_session.add(_template(theirs, "analyzer", is_default=True))
    await db_session.flush()

    with tenant_isolation_bypass(
        db_session,
        reason="BE-9357: assert the repository's own WHERE clause, not the guard's injected one",
        models=(AgentTemplate,),
    ):
        found = await MissionRepository().get_template_by_role(db_session, mine, "analyzer")

    assert found is None, (
        "get_template_by_role's is_default branch selects another tenant's template on its "
        "own SQL. Only the tenant guard is stopping it from being returned."
    )


@pytest.mark.asyncio
async def test_own_live_default_template_still_resolves(db_session):
    tenant = _tenant()
    live = _template(tenant, "analyzer", is_default=True)
    db_session.add(live)
    await db_session.flush()

    with tenant_isolation_bypass(
        db_session,
        reason="BE-9357: assert the repository's own WHERE clause, not the guard's injected one",
        models=(AgentTemplate,),
    ):
        found = await MissionRepository().get_template_by_role(db_session, tenant, "analyzer")

    assert found is not None and found.id == live.id
