# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




async def _seed_org_product(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9083d", tenant_key=tenant_key, is_active=True
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
        name=f"BE-9083d {uuid.uuid4().hex[:8]}",
        description="phase-scope + section fetch cell",
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
) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="BE-9083d mission",
        status="active",
        created_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=agent_display_name,
        status="working",
        started_at=now,
    )
    db_session.add(execution)
    await db_session.commit()
    return job.job_id


async def _seed_active_run(db_session, tenant_key: str, project_ids: list[str]) -> None:
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
            conductor_agent_id=str(uuid.uuid4()),
            project_statuses=dict.fromkeys(project_ids, "pending"),
        )
    )
    await db_session.commit()


async def _mission_result(client, job_id: str, **extra_args):
    async with client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, **extra_args})
        assert result.is_error is False, _error_text(result)
        return _payload(result)


async def _seed_suborch(mcp_client_tuple, *, implementation_launched: bool) -> tuple:
    client, tenant_key, db_session = mcp_client_tuple
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session,
        tenant_key,
        product_id,
        implementation_launched=implementation_launched,
        staging_status="staging_complete" if implementation_launched else "staging",
    )
    await _seed_active_run(db_session, tenant_key, [project_id])
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )
    return client, job_id




async def test_staging_suborch_fetch_keeps_bridge_and_drops_implementation_regions(mcp_client):
    client, job_id = await _seed_suborch(mcp_client, implementation_launched=False)

    payload = await _mission_result(client, job_id)

    assert payload["project_phase"] == "staging"
    joined = "\n".join(payload["next_required_actions"])
    assert "get_job_mission ONCE" in joined
    assert "no gate" in joined
    protocol = payload["full_protocol"]
    assert "call get_job_mission ONCE" in protocol
    assert "5. CONTINUE TO IMPLEMENTATION (no gate, no wait)" in protocol
    assert "Do NOT wait for a human" in protocol
    assert "THE COORDINATION LOOP" not in protocol
    assert "### RESTING STATES" not in protocol
    assert "Closeout steps (order matters):" not in protocol


async def test_implementation_suborch_fetch_serves_implementation_regions(mcp_client):
    client, job_id = await _seed_suborch(mcp_client, implementation_launched=True)

    payload = await _mission_result(client, job_id)

    assert payload["project_phase"] == "implementation"
    protocol = payload["full_protocol"]
    assert "THE COORDINATION LOOP" in protocol
    assert "Closeout steps (order matters):" in protocol
    assert "2. READ YOUR CONTRACT" not in protocol
    assert "STAGING -- ALREADY COMPLETE" in protocol
    assert "7. CLOSE OUT + REPORT" in protocol




async def test_default_response_carries_protocol_toc(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(
        db_session, tenant_key, product_id, implementation_launched=True, staging_status="staging_complete"
    )
    job_id = await _seed_job(
        db_session, tenant_key, project_id, job_type="implementer", agent_display_name="implementer"
    )

    payload = await _mission_result(client, job_id)

    toc = payload["protocol_toc"]
    assert toc, "the default response must advertise the section TOC"
    assert all(set(e) >= {"section", "chars", "lines"} for e in toc)
    assert sum(e["chars"] for e in toc) == len(payload["full_protocol"])
    assert "section=" in payload["truncation_check"]


async def test_section_fetch_returns_byte_identical_slice(mcp_client):
    client, job_id = await _seed_suborch(mcp_client, implementation_launched=True)

    full = await _mission_result(client, job_id)
    toc = full["protocol_toc"]
    protocol = full["full_protocol"]

    offset = 0
    slices: dict[str, str] = {}
    for entry in toc:
        slices[entry["section"]] = protocol[offset : offset + entry["chars"]]
        offset += entry["chars"]
    assert offset == len(protocol)

    for target in (toc[len(toc) // 2]["section"], toc[-1]["section"]):
        section_payload = await _mission_result(client, job_id, section=target)
        assert section_payload["protocol_section"] == target
        assert section_payload["protocol_section_content"] == slices[target], (
            f"section {target!r} is not byte-identical to the full-render slice"
        )
        assert section_payload["full_protocol"] is None
        assert section_payload["mission"] is None
        assert section_payload["agent_identity"] is None
        assert section_payload["protocol_toc"] == toc
        assert section_payload["next_required_actions"]


async def test_unknown_section_is_rejected_with_valid_names(mcp_client):
    client, job_id = await _seed_suborch(mcp_client, implementation_launched=True)
    full = await _mission_result(client, job_id)
    a_valid_name = full["protocol_toc"][0]["section"]

    async with client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, "section": "no_such_section"})
        assert result.is_error is True
        text = _error_text(result)
        assert "no_such_section" in text
        assert a_valid_name in text, "the rejection must list the valid section names"


async def test_section_fetch_wins_over_etag_match(mcp_client):
    client, job_id = await _seed_suborch(mcp_client, implementation_launched=True)
    full = await _mission_result(client, job_id)
    target = full["protocol_toc"][0]["section"]

    payload = await _mission_result(client, job_id, protocol_etag=full["protocol_etag"], section=target)

    assert payload["protocol_section"] == target
    assert payload["protocol_section_content"]
    assert payload["full_protocol"] is None


async def test_etag_match_without_section_still_strips_toc_with_the_block(mcp_client):
    client, job_id = await _seed_suborch(mcp_client, implementation_launched=True)
    full = await _mission_result(client, job_id)

    async with client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, "protocol_etag": full["protocol_etag"]})
        assert result.is_error is False, _error_text(result)
        raw = _raw_text(result)
        payload = _payload(result)

    assert payload["protocol_unchanged"] is True
    assert payload["full_protocol"] is None
    assert '"protocol_toc"' not in raw
    assert '"protocol_section"' not in raw
