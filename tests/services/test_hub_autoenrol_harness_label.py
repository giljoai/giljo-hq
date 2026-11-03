# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.models.comm import CommParticipant
from tests.services.test_tsk9459_orchestrator_joins_own_thread import (
    _bound_thread_id,
    _mission_service,
    _seed_orchestrator,
)
from tests.unit.test_be6008_staged_agent_mailboxes import _seed_project


pytestmark = pytest.mark.asyncio


async def _harness_of(db_session, tenant_key: str, thread_id: str, agent_id: str) -> str | None:
    rows = await db_session.execute(
        select(CommParticipant.harness).where(
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.thread_id == thread_id,
            CommParticipant.participant_id == agent_id,
        )
    )
    return rows.scalar_one()


async def _seeded(db_session):
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, execution_mode="multi_terminal", implementation_launched=True
    )
    job_id, agent_id = await _seed_orchestrator(db_session, tenant_key, project_id)
    return tenant_key, project_id, job_id, agent_id


async def test_a_mission_fetch_enrols_with_the_hub_label(db_session):
    tenant_key, project_id, job_id, agent_id = await _seeded(db_session)

    await _mission_service(db_session).get_agent_mission(
        job_id=job_id, tenant_key=tenant_key, detected_harness="generic", hub_harness="chatgpt"
    )

    thread_id = await _bound_thread_id(db_session, tenant_key, project_id)
    assert await _harness_of(db_session, tenant_key, thread_id, agent_id) == "chatgpt"


async def test_without_a_hub_label_the_render_harness_is_kept(db_session):
    tenant_key, project_id, job_id, agent_id = await _seeded(db_session)

    await _mission_service(db_session).get_agent_mission(
        job_id=job_id, tenant_key=tenant_key, detected_harness="claude-code"
    )

    thread_id = await _bound_thread_id(db_session, tenant_key, project_id)
    assert await _harness_of(db_session, tenant_key, thread_id, agent_id) == "claude-code"
