# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9083a — next_required_actions + truncation sentinels, proven at the MCP transport.

The checklist is an authoritative steering wheel computed per (phase x role) cell;
a wrong cell is an authoritative WRONG steering wheel (CE-0026 frozen-phase
precedent), and the BE-5042 rule says the failing layer for instruction-delivery
bugs is the MCP boundary. So every cell is exercised through the REAL FastMCP
transport (``create_connected_server_and_client_session``), one test per cell:

  1. worker                          (get_job_mission)
  2. solo orchestrator staging      (get_staging_instructions)
  3. solo orchestrator implementation (get_job_mission)
  4. chain sub-orch staging         (get_job_mission, §14 ungated)
  5. chain sub-orch implementation  (get_job_mission)
  6. project-less chain conductor   (get_job_mission)

Plus the truncation-survival wire shape: the checklist + truncation_check serialize
BEFORE the multi-KB blocks, full_protocol ends with the END-OF-PROTOCOL tail marker,
and an etag-match response strips the sentinel with the block it describes.

Parallel-safe: DB-touching tests use the db_session fixture (TransactionalTestContext,
rollback at teardown). No module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.protocol_survival import PROTOCOL_END_MARKER
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(_raw_text(result))


def _raw_text(result) -> str:
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return text


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


# ---------------------------------------------------------------------------
# Transport fixture (mirrors test_be9035b_detected_harness_mcp_boundary)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_org_product(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9083a", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id


async def _seed_project(
    db_session,
    tenant_key: str,
    product_id: str,
    *,
    implementation_launched: bool,
    staging_status: str,
) -> str:
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-9083a {uuid.uuid4().hex[:8]}",
        description="truncation survival cell",
        mission="build it",
        status="active",
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
        execution_mode="multi_terminal",
        implementation_launched_at=now if implementation_launched else None,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project.id


async def _seed_job(
    db_session,
    tenant_key: str,
    project_id: str | None,
    *,
    job_type: str,
    agent_display_name: str,
    agent_id: str | None = None,
) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="BE-9083a mission",
        status="active",
        created_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=agent_id or str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=agent_display_name,
        status="working",
        started_at=now,
    )
    db_session.add(execution)
    await db_session.commit()
    return job.job_id


async def _seed_active_run(db_session, tenant_key: str, project_ids: list[str], conductor_agent_id: str) -> None:
    db_session.add(
        SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_ids=project_ids,
            resolved_order=project_ids,
            current_index=0,
            execution_mode="multi_terminal",
            status="running",
            locked=True,
            conductor_agent_id=conductor_agent_id,
            project_statuses=dict.fromkeys(project_ids, "pending"),
        )
    )
    await db_session.commit()


async def _mission_result(client, job_id: str, **extra_args):
    async with client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, **extra_args})
        assert result.is_error is False, _error_text(result)
        return _payload(result), _raw_text(result)


# ---------------------------------------------------------------------------
# Cell 1 — worker (+ the truncation-survival wire shape rides along)
# ---------------------------------------------------------------------------


async def test_worker_cell_and_wire_shape(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=True, staging_status="staging_complete"
    )
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="implementer", agent_display_name="implementer"
    )

    payload, raw = await _mission_result(client, job_id)

    checklist = payload["next_required_actions"]
    joined = "\n".join(checklist)
    assert len(checklist) <= 15
    assert "report_progress" in joined
    assert "complete_job" in joined
    assert "write_project_closeout" not in joined

    # Tail sentinel: the FINAL full_protocol ends with the marker line.
    assert payload["full_protocol"].endswith(PROTOCOL_END_MARKER)
    # Head sentinel present and honest about the size + recovery.
    assert "protocol_etag" in payload["truncation_check"]
    assert PROTOCOL_END_MARKER in payload["truncation_check"]

    # Wire ORDER (the actual serialized bytes): the survival fields come BEFORE the
    # multi-KB blocks, and full_protocol is the last large field.
    for early in ('"next_required_actions"', '"truncation_check"', '"project_phase"'):
        assert raw.index(early) < raw.index('"mission"')
        assert raw.index(early) < raw.index('"agent_identity"')
        assert raw.index(early) < raw.index('"full_protocol"')


async def test_etag_match_strips_block_and_sentinel_but_keeps_checklist(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=True, staging_status="staging_complete"
    )
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="implementer", agent_display_name="implementer"
    )

    first, _ = await _mission_result(client, job_id)
    second, raw = await _mission_result(client, job_id, protocol_etag=first["protocol_etag"])

    assert second["protocol_unchanged"] is True
    assert second["full_protocol"] is None
    # The head sentinel describes the omitted block — it must be stripped with it.
    assert '"truncation_check"' not in raw
    # The checklist survives on the small response (it is the recovery payload).
    assert second["next_required_actions"]


# ---------------------------------------------------------------------------
# Cell 2 — solo orchestrator, staging (get_staging_instructions)
# ---------------------------------------------------------------------------


async def test_solo_orchestrator_staging_cell(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=False, staging_status="staging"
    )
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )

    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        raw = _raw_text(result)

    joined = "\n".join(payload["next_required_actions"])
    assert "update_project_mission" in joined
    assert "spawn_job" in joined
    assert "Implement" in joined, "solo staging must end at the human Implement gate"
    assert "Hub" not in joined, "solo staging must not carry chain Hub steps"
    # Early on the wire: before the big protocol block.
    assert raw.index('"next_required_actions"') < raw.index('"orchestrator_protocol"')


# ---------------------------------------------------------------------------
# Cell 3 — solo orchestrator, implementation (get_job_mission)
# ---------------------------------------------------------------------------


async def test_solo_orchestrator_implementation_cell(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=True, staging_status="staging_complete"
    )
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )

    payload, _ = await _mission_result(client, job_id)

    assert payload["project_phase"] == "implementation"
    joined = "\n".join(payload["next_required_actions"])
    assert "get_workflow_status" in joined
    assert "write_project_closeout" in joined
    assert "Hub" not in joined, "solo has no chain Hub protocol"


# ---------------------------------------------------------------------------
# Cells 4 + 5 — chain sub-orchestrator, staging / implementation
# ---------------------------------------------------------------------------


async def test_chain_suborch_staging_cell(mcp_client):
    """§14: a chain sub-orch is UNGATED during its own staging — get_job_mission
    delivers the mission plus the STAGING checklist (live phase, not the frozen
    snapshot), including the protocol_etag refetch step."""
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=False, staging_status="staging"
    )
    await _seed_active_run(db_session, tenant_key, [project_id], conductor_agent_id=str(uuid.uuid4()))
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )

    payload, _ = await _mission_result(client, job_id)

    assert payload["project_phase"] == "staging"
    joined = "\n".join(payload["next_required_actions"])
    assert "update_project_mission" in joined
    assert "INERT" in joined
    assert "protocol_etag" in joined
    assert "Implement" not in joined, "chain mode has no human Implement gate"


async def test_chain_suborch_implementation_cell(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=True, staging_status="staging_complete"
    )
    await _seed_active_run(db_session, tenant_key, [project_id], conductor_agent_id=str(uuid.uuid4()))
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )

    payload, _ = await _mission_result(client, job_id)

    assert payload["project_phase"] == "implementation"
    joined = "\n".join(payload["next_required_actions"])
    assert "write_project_closeout" in joined
    assert "Hub" in joined
    assert joined.index("complete_job") < joined.index("write_project_closeout")


# ---------------------------------------------------------------------------
# Cell 6 — project-less chain conductor
# ---------------------------------------------------------------------------


async def test_conductor_cell(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=False, staging_status="staging"
    )
    conductor_agent_id = str(uuid.uuid4())
    await _seed_active_run(db_session, tenant_key, [project_id], conductor_agent_id=conductor_agent_id)
    job_id = await _seed_job(
        db_session,
        tenant_key,
        None,
        job_type="orchestrator",
        agent_display_name="orchestrator",
        agent_id=conductor_agent_id,
    )

    payload, _ = await _mission_result(client, job_id)

    joined = "\n".join(payload["next_required_actions"])
    assert "ready_to_advance" in joined, "the conductor checklist must name the ONE authoritative advance signal"
    assert "update_project_mission" not in joined, "the conductor owns no project mission"
    # BE-9083a critical-first reorder: the chain chapters lead the protocol, and the
    # tail marker still terminates it.
    protocol = payload["full_protocol"]
    assert protocol.index("CH_CHAIN_DRIVE") < len(protocol) // 2, "chain drive must ride in the payload HEAD"
    assert protocol.endswith(PROTOCOL_END_MARKER)
