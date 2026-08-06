# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9357 -- two more role-resolution reads that still returned trashed templates.

BE-9325 swept ``MissionRepository.get_template_by_id`` and ``get_active_templates``
and annotated both. It walked past ``get_template_by_role``, which sits literally
between them and carries the identical defect on both of its branches.

``template_cache.TemplateCache`` carried the same defect and was fixed here too,
alongside a test that pinned its unreachability. BE-9358 proved that module a
confirmed orphan -- one construction site, gated on a ``db_manager`` no shipped
code ever passed -- and deleted it, so those four tests went with it. What remains
is the repository half, which is live.

Real-database tests: the defect is in the WHERE clause, so only real rows can see it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.mission_repository import MissionRepository
from giljo_mcp.tenant_guard import tenant_isolation_bypass, tenant_session_context


def _tenant() -> str:
    """A tenant key no other test (or xdist worker) shares."""
    return f"be9357-{uuid4().hex[:16]}"


def _template(
    tenant_key: str,
    role: str,
    *,
    deleted: bool = False,
    is_default: bool = False,
) -> AgentTemplate:
    """A minimally-valid *active* template row, optionally already trashed.

    ``is_active=True`` on a trashed row is not a contrivance -- it is exactly what
    soft-delete leaves behind (``template_service`` stamps ``deleted_at`` and stops),
    and it is the whole bug.
    """
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


# ============================================================================
# MissionRepository.get_template_by_role -- branch 1 (tenant-specific)
# ============================================================================


@pytest.mark.asyncio
async def test_trashed_tenant_template_is_not_resolved_by_role(db_session):
    """A deleted agent must not come back as the tenant's template for its role."""
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
    """Live-row control: a fix that excluded trashed rows by excluding *everything*
    would pass the test above. This is the assertion that catches it."""
    tenant = _tenant()
    live = _template(tenant, "implementer")
    db_session.add(live)
    await db_session.flush()

    with tenant_session_context(db_session, tenant):
        found = await MissionRepository().get_template_by_role(db_session, tenant, "implementer")

    assert found is not None and found.id == live.id


# ============================================================================
# MissionRepository.get_template_by_role -- branch 2 (is_default fallback)
# ============================================================================


@pytest.mark.asyncio
async def test_trashed_default_template_is_not_resolved_by_role(db_session):
    """The is_default fallback must not resurrect a trashed default either."""
    tenant = _tenant()
    db_session.add(_template(tenant, "tester", deleted=True, is_default=True))
    await db_session.flush()

    with tenant_session_context(db_session, tenant):
        found = await MissionRepository().get_template_by_role(db_session, tenant, "tester")

    assert found is None, "A trashed is_default template is still resolved for its role."


@pytest.mark.asyncio
async def test_is_default_branch_scopes_to_the_calling_tenant(db_session):
    """The is_default branch carried no ``tenant_key`` predicate at all.

    Deliberately scoped claim: this is defence in depth, NOT a live cross-tenant leak.
    ``tenant_guard._enforce_tenant_scope`` injects a ``with_loader_criteria`` tenant
    filter into *every* SELECT that touches a tenant-scoped model, so a real caller's
    session never actually reads another tenant's row through this query. The guard is
    what makes the missing predicate survivable -- it is not what makes it correct, and
    "every database query MUST filter by tenant_key" has no exception for "something
    else also filters it."

    So the guard is bypassed here on purpose: with it active this query cannot be
    observed at all, and a repository test that only passes because a different layer
    saved it is not a test of this repository.
    """
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
    """Live-row control: adding the predicates must not make a tenant's own live default
    template stop resolving. The seeder writes every tenant its own ``is_default=True``
    rows under that tenant's own key (``template_seeder`` passes the real ``tenant_key``;
    nothing anywhere writes ``tenant_key="system"``), so this is the row a real tenant has.

    Precise about what it covers: this resolves on branch 1, not branch 2. Once branch 2
    carries the tenant predicate its WHERE clause is a strict superset of branch 1's, so no
    row reaches branch 2 that branch 1 would have missed -- a branch-2 live control cannot
    be written, and this docstring should not imply otherwise."""
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
