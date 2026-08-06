# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.

"""BE-9325 -- a trashed agent template must drop out of spawn resolution.

Soft-delete stamps ``deleted_at`` and deliberately leaves ``is_active`` alone
(``template_service.py:720``). ``AgentCompletionRepository.get_template_by_name``
filters on ``name + tenant_key + is_active`` and never looks at ``deleted_at``
(``agent_completion_repository.py:550-559``), so a trashed row still satisfies it.

These are REAL-DATABASE tests on purpose. The existing spawn-resolution coverage
in ``tests/unit/test_job_lifecycle_service.py`` mocks ``scalar_one_or_none``
directly, which means it asserts against a stubbed return value and can never
observe what the SQL actually selects -- the defect lives in the WHERE clause, so
only real rows can catch it.

The project's own instruction was to reproduce consequence 3 before fixing it:
the ``MultipleResultsFound`` raise was traced through the code but never
executed, so it was INFERRED, not OBSERVED. These tests execute it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import MultipleResultsFound

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository


def _template(tenant_key: str, name: str, *, deleted: bool = False) -> AgentTemplate:
    """A minimally-valid active template row, optionally already trashed.

    ``is_active=True`` on a trashed row is not a contrivance for the test -- it
    is exactly what soft-delete leaves behind, and it is the whole bug.
    """
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        category="custom",
        system_instructions="sys",
        user_instructions="user",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        deleted_at=datetime.now(UTC) if deleted else None,
    )


@pytest.mark.asyncio
async def test_trashed_template_is_not_resolved_at_spawn(db_session, test_tenant_key):
    """Consequence 1: a deleted agent must not become a live agent's identity.

    One template, trashed, nothing else. The spawn lookup must not find it --
    if it does, a spawn stamps the trashed template's id onto the AgentJob and
    ``get_job_mission`` renders the deleted agent's instructions as the running
    agent's identity.
    """
    name = f"be9325-solo-{uuid4().hex[:8]}"
    db_session.add(_template(test_tenant_key, name, deleted=True))
    await db_session.flush()

    found = await AgentCompletionRepository().get_template_by_name(db_session, test_tenant_key, name)

    assert found is None, (
        "A soft-deleted template still resolves at spawn resolution. The user deleted this "
        "agent; the system is still willing to make it a live agent's operating identity."
    )


@pytest.mark.asyncio
async def test_delete_then_recreate_at_same_name_still_spawns(db_session, test_tenant_key):
    """Consequence 3, the one that was inferred and never executed.

    Delete an agent, create a new one at the same name, activate it -- an ordinary
    maintenance sequence that nothing prevents (the collision check and the partial
    unique index both exclude deleted rows). Two rows then match
    ``name + tenant_key + is_active``, and ``scalar_one_or_none()`` raises.

    Before the fix this raises ``MultipleResultsFound``, which
    ``job_lifecycle_service`` converts into a generic "Failed to spawn agent"
    pointing at nothing -- permanently, for that agent name.
    """
    name = f"be9325-recreated-{uuid4().hex[:8]}"
    trashed = _template(test_tenant_key, name, deleted=True)
    live = _template(test_tenant_key, name)
    db_session.add_all([trashed, live])
    await db_session.flush()

    try:
        found = await AgentCompletionRepository().get_template_by_name(db_session, test_tenant_key, name)
    except MultipleResultsFound:  # pragma: no cover - the pre-fix path
        pytest.fail(
            "Delete-then-recreate at the same name raises MultipleResultsFound in the spawn "
            "lookup. Every spawn of this agent name fails from here on, the user cannot "
            "diagnose it from the UI, and they did nothing wrong."
        )

    assert found is not None, "The live recreated template must still resolve."
    assert found.id == live.id, (
        "The spawn lookup picked the TRASHED row over the live one. A deleted agent's "
        "instructions would become the running agent's identity."
    )


@pytest.mark.asyncio
async def test_live_template_still_resolves(db_session, test_tenant_key):
    """Regression guard: the fix must not break the ordinary case.

    Cheap, and it is the assertion that catches an over-broad filter -- a fix that
    excludes trashed rows by excluding everything would pass both tests above.
    """
    name = f"be9325-live-{uuid4().hex[:8]}"
    live = _template(test_tenant_key, name)
    db_session.add(live)
    await db_session.flush()

    found = await AgentCompletionRepository().get_template_by_name(db_session, test_tenant_key, name)

    assert found is not None and found.id == live.id
