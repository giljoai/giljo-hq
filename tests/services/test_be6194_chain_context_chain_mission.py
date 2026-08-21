# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6194: ChainContext.chain_mission — additive read-through field.

A later combined sub-orch script needs the LIVE chain mission injected into the
sub-orchestrator's runtime protocol (no stale snapshot). The resolver reads it
straight off the already-serialized run dict (sequence_runs.chain_mission, BE-6185);
no extra DB read.

1. test_chain_context_has_chain_mission_field (unit)
   ChainContext carries chain_mission when supplied; defaults None when omitted.

2. test_resolve_populates_chain_mission (DB-touching)
   resolve_for_conductor surfaces the run's written chain_mission.

3. test_solo_resolve_chain_mission_none (DB-touching)
   A project in no active run -> resolve() returns None (solo byte-identical;
   nothing to read).

Parallel-safe: DB-touching tests use db_session (TransactionalTestContext). No
module-level mutable state. Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, Project
from giljo_mcp.services.sequence_chain_context import ChainContext, SequenceChainContextResolver
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-6194 {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        # BE-9429: uq_project_taxonomy_active is NULLS NOT DISTINCT, so these
        # NULL-product/NULL-type rows collide unless the serial differs.
        series_number=next_series_number(),
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


def _run_svc(session: AsyncSession) -> SequenceRunService:
    return SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session)


def _resolver(session: AsyncSession) -> SequenceChainContextResolver:
    return SequenceChainContextResolver(
        db_manager=None,
        tenant_manager=TenantManager(),
        test_session=session,
    )


# ---------------------------------------------------------------------------
# 1. ChainContext carries chain_mission; defaults None when omitted
# ---------------------------------------------------------------------------


def test_chain_context_has_chain_mission_field() -> None:
    ctx = ChainContext(
        run_id="r",
        role="conductor",
        current_index=0,
        resolved_order=["p"],
        is_staging=False,
        conductor_agent_id="c",
        chain_mission="the plan",
    )
    assert ctx.chain_mission == "the plan"

    default_ctx = ChainContext(
        run_id="r",
        role="conductor",
        current_index=0,
        resolved_order=["p"],
        is_staging=False,
        conductor_agent_id="c",
    )
    assert default_ctx.chain_mission is None


# ---------------------------------------------------------------------------
# 2. resolve_for_conductor surfaces the written chain mission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_populates_chain_mission(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    p1 = await _seed_project(db_session, tenant)
    p2 = await _seed_project(db_session, tenant)

    run = await _run_svc(db_session).create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode="claude_code_cli",
        tenant_key=tenant,
    )
    # BE-6185 ultralock: a freshly-created 'pending' run is NOT ultralocked, so the
    # conductor-owned chain_mission write succeeds.
    await _run_svc(db_session).update(
        run_id=run["id"],
        tenant_key=tenant,
        chain_mission="ship the whole chain end to end",
    )

    conductor_agent_id = run["conductor_agent_id"]
    chain_ctx = await _resolver(db_session).resolve_for_conductor(
        db_session,
        conductor_agent_id=conductor_agent_id,
        tenant_key=tenant,
    )

    assert chain_ctx is not None
    assert chain_ctx.chain_mission == "ship the whole chain end to end"


# ---------------------------------------------------------------------------
# 3. solo project in no active run -> resolve() returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solo_resolve_chain_mission_none(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)

    chain_ctx = await _resolver(db_session).resolve(
        db_session,
        project_id=pid,
        tenant_key=tenant,
        orchestrator_agent_id=str(uuid.uuid4()),
        is_staging=False,
    )

    assert chain_ctx is None, "a project in no active run resolves to None (solo byte-identical)"
