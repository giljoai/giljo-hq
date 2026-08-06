# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9325 -- the mission read path also resolved trashed agent templates.

Found by an independent adversarial audit of the first BE-9325 fix, which had
claimed "exactly four sites." It was five and six.

``MissionRepository.get_template_by_id`` is the worse of the two. ``AgentJob.template_id``
is only nulled at the 30-day hard purge (``template_service.nullify_job_template_refs``),
never at soft-delete (``template_service.py:720`` stamps ``deleted_at`` and stops), so a
job already bound to a template the user later deletes keeps rendering that template's
instructions as its live identity on every ``get_job_mission`` call -- for up to 30 days,
with nothing in the UI to say so. That is the exact scenario where deleting an agent
matters most: the operator deletes it *because* its instructions are wrong.

``get_active_templates`` feeds the roster of agents the orchestrator is told it may
spawn. A trashed template stayed on that roster, so the orchestrator would offer a
deleted agent, spawn it, and (correctly, post-fix) resolve nothing.

Real-database tests: the defect is in the WHERE clause, so only real rows can see it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.mission_repository import MissionRepository


def _template(tenant_key: str, name: str, *, deleted: bool = False) -> AgentTemplate:
    """A minimally-valid active template row, optionally already trashed.

    ``is_active=True`` on a trashed row is not a contrivance -- it is exactly what
    soft-delete leaves behind, and it is the whole bug.
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
async def test_trashed_template_is_not_resolved_by_id_for_a_bound_job(db_session, test_tenant_key):
    """A job bound to a since-deleted template must not keep rendering its identity."""
    trashed = _template(test_tenant_key, f"be9325-mission-{uuid4().hex[:8]}", deleted=True)
    db_session.add(trashed)
    await db_session.flush()

    found = await MissionRepository().get_template_by_id(db_session, test_tenant_key, trashed.id)

    assert found is None, (
        "get_job_mission still resolves a soft-deleted template by id. The agent bound to it "
        "keeps operating under the deleted agent's instructions until the 30-day purge, and "
        "nothing tells the operator that the delete did not take effect."
    )


@pytest.mark.asyncio
async def test_live_template_still_resolves_by_id(db_session, test_tenant_key):
    """Regression guard: a fix that excluded trashed rows by excluding everything would
    pass the test above. This is the assertion that catches it."""
    live = _template(test_tenant_key, f"be9325-mission-live-{uuid4().hex[:8]}")
    db_session.add(live)
    await db_session.flush()

    found = await MissionRepository().get_template_by_id(db_session, test_tenant_key, live.id)

    assert found is not None and found.id == live.id


@pytest.mark.asyncio
async def test_trashed_template_is_off_the_orchestrator_roster(db_session, test_tenant_key):
    """The roster of spawnable agents must not advertise one the user deleted."""
    trashed = _template(test_tenant_key, f"be9325-roster-trashed-{uuid4().hex[:8]}", deleted=True)
    live = _template(test_tenant_key, f"be9325-roster-live-{uuid4().hex[:8]}")
    db_session.add_all([trashed, live])
    await db_session.flush()

    templates = await MissionRepository().get_active_templates(db_session, test_tenant_key, limit=50)
    names = {t.name for t in templates}

    assert trashed.name not in names, (
        "A deleted agent is still offered to the orchestrator as available to spawn. It would "
        f"pick it, spawn it, and resolve no template at all. Roster: {sorted(names)}"
    )
    assert live.name in names, "The live template must still be on the roster."
