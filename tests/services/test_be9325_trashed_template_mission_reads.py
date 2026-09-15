# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.mission_repository import MissionRepository


def _template(tenant_key: str, name: str, *, deleted: bool = False) -> AgentTemplate:
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
    live = _template(test_tenant_key, f"be9325-mission-live-{uuid4().hex[:8]}")
    db_session.add(live)
    await db_session.flush()

    found = await MissionRepository().get_template_by_id(db_session, test_tenant_key, live.id)

    assert found is not None and found.id == live.id


@pytest.mark.asyncio
async def test_trashed_template_is_off_the_orchestrator_roster(db_session, test_tenant_key):
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
