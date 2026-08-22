# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9491 -- ``AgentOperationsRepository.get_terminal_agent_ids``, the batch
liveness check that powers the Hub broadcast/direct fan-out filter.

An agent_id is terminal only when EVERY ``AgentExecution`` row it owns is
complete/closed/decommissioned. Three properties matter and each gets its own
test: (1) a mix of live/terminal agent_ids is classified correctly, (2) a
succession pair (terminal execution, then a LATER active one under the same
agent_id) must NOT be flagged terminal -- the respawn trap, (3) an agent_id
with ZERO execution rows must NOT be flagged terminal -- the headless-agent
trap (a never-tracked agent, or a human user_id sharing this id space via
MessageRecipient.agent_id, must never be silently excluded).

DB-touching: db_session (TransactionalTestContext). No module-level mutable
state. Parallel-safe (pytest-xdist). Edition Scope: CE.
"""

from __future__ import annotations

import random
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.repositories.agent_operations_repository import AgentOperationsRepository


pytestmark = pytest.mark.asyncio


async def _seed_project(db_session: AsyncSession, tenant_key: str) -> Project:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"BE-9491 Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9491 terminal-agent-ids project",
        description="d",
        mission="m",
        status="active",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _seed_execution(
    db_session: AsyncSession,
    tenant_key: str,
    project_id: str,
    *,
    agent_id: str,
    status: str,
) -> None:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="do work",
        status="active",
    )
    db_session.add(job)
    db_session.add(
        AgentExecution(
            job_id=job.job_id,
            agent_id=agent_id,
            tenant_key=tenant_key,
            status=status,
            agent_display_name="implementer",
        )
    )


async def test_mix_of_live_and_terminal_agent_ids_classified_correctly(db_session: AsyncSession, test_tenant_key: str):
    project = await _seed_project(db_session, test_tenant_key)
    terminal_agent = str(uuid.uuid4())
    live_agent = str(uuid.uuid4())
    await _seed_execution(db_session, test_tenant_key, project.id, agent_id=terminal_agent, status="complete")
    await _seed_execution(db_session, test_tenant_key, project.id, agent_id=live_agent, status="working")
    await db_session.commit()

    repo = AgentOperationsRepository()
    result = await repo.get_terminal_agent_ids(db_session, test_tenant_key, [terminal_agent, live_agent])

    assert result == {terminal_agent}


async def test_succession_pair_terminal_then_active_is_not_flagged_terminal(
    db_session: AsyncSession, test_tenant_key: str
):
    """The respawn trap: one agent_id owns TWO executions -- an earlier one that
    finished, and a later one still active. Must NOT be treated as dead."""
    project = await _seed_project(db_session, test_tenant_key)
    respawned_agent = str(uuid.uuid4())
    await _seed_execution(db_session, test_tenant_key, project.id, agent_id=respawned_agent, status="complete")
    await _seed_execution(db_session, test_tenant_key, project.id, agent_id=respawned_agent, status="working")
    await db_session.commit()

    repo = AgentOperationsRepository()
    result = await repo.get_terminal_agent_ids(db_session, test_tenant_key, [respawned_agent])

    assert result == set(), "an agent_id with any active execution must never be flagged terminal"


async def test_agent_id_with_zero_execution_rows_is_not_flagged_terminal(
    db_session: AsyncSession, test_tenant_key: str
):
    """The headless-agent trap: an id that was never tracked by the job system
    (or a human user_id sharing this column) must be treated as live, not dead --
    a single ``NOT EXISTS(active row)`` shortcut would be vacuously true here."""
    repo = AgentOperationsRepository()
    never_tracked_id = str(uuid.uuid4())

    with tenant_session_context(db_session, test_tenant_key):
        result = await repo.get_terminal_agent_ids(db_session, test_tenant_key, [never_tracked_id])

    assert result == set()


async def test_empty_agent_ids_returns_empty_set_without_a_query(db_session: AsyncSession, test_tenant_key: str):
    repo = AgentOperationsRepository()
    result = await repo.get_terminal_agent_ids(db_session, test_tenant_key, [])
    assert result == set()


async def test_terminal_agent_id_from_a_different_tenant_is_not_flagged(db_session: AsyncSession):
    """Tenant isolation: an agent_id that is entirely terminal under tenant A must
    not leak into tenant B's terminal set just because the id string collides."""
    project_a = await _seed_project(db_session, "tenant-a-be9491")
    shared_id = str(uuid.uuid4())
    await _seed_execution(db_session, "tenant-a-be9491", project_a.id, agent_id=shared_id, status="complete")
    await db_session.commit()

    repo = AgentOperationsRepository()
    with tenant_session_context(db_session, "tenant-b-be9491"):
        result = await repo.get_terminal_agent_ids(db_session, "tenant-b-be9491", [shared_id])

    assert result == set()
