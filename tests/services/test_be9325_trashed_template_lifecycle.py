# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import MultipleResultsFound

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository


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
async def test_trashed_template_is_not_resolved_at_spawn(db_session, test_tenant_key):
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
    name = f"be9325-live-{uuid4().hex[:8]}"
    live = _template(test_tenant_key, name)
    db_session.add(live)
    await db_session.flush()

    found = await AgentCompletionRepository().get_template_by_name(db_session, test_tenant_key, name)

    assert found is not None and found.id == live.id
