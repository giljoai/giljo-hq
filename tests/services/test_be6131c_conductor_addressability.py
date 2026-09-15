# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_chain_drive,
)
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


_CONDUCTOR_MARKER = "YOU ARE ADDRESSABLE: USER DIRECTIVE RELAY"
_INBOX_POLL_MARKER = "get_thread_history"
_INBOX_POLL_CURSOR_MARKER = "unread_only=true"

_FORBIDDEN_WORKER_CALLS = ("set_next_actor", "comm_threads")




async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
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
        name=f"BE-6131c test {uuid.uuid4().hex[:6]}",
        description="Conductor addressability test project.",
        mission="Run sequential projects as conductor.",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        series_number=1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
        implementation_launched_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _spawn_conductor(session: AsyncSession, tenant_key: str, project_id: str) -> tuple[str, str]:
    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=session,
    )
    result = await lifecycle.spawn_job(
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Drive sequential run as conductor.",
    )
    row = await session.execute(
        select(AgentExecution).where(
            AgentExecution.tenant_key == tenant_key,
            AgentExecution.job_id == result.job_id,
        )
    )
    execution = row.scalar_one()
    return result.job_id, str(execution.agent_id)




@pytest.mark.asyncio
async def test_conductor_addressable_inbox_polled(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    project_id = await _seed_project(db_session, tenant)
    _job_id, agent_id = await _spawn_conductor(db_session, tenant, project_id)

    assert agent_id is not None, "Conductor AgentExecution must carry a non-null agent_id"
    uuid.UUID(agent_id)

    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)

    comm = CommThreadService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        session=db_session,
    )
    thread = await comm.resolve_or_create_bound_thread(project_id=project_id, tenant_key=tenant)
    await comm.join_thread(thread_id=thread["thread_id"], participant_id=agent_id, tenant_key=tenant)
    post_result = await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="DIRECTIVE: pause after project 2 and confirm before continuing.",
        from_agent="user",
        to_participant=agent_id,
        requires_action=True,
        tenant_key=tenant,
    )
    assert post_result["recipients"] == [agent_id], (
        "Directive posted to the conductor agent_id must be accepted as a single directed recipient"
    )

    history = await comm.get_thread_history(
        thread_id=thread["thread_id"],
        as_participant=agent_id,
        tenant_key=tenant,
    )
    contents = [m.get("content", "") for m in history["messages"]]
    assert any("DIRECTIVE" in c for c in contents), (
        f"Directive posted to conductor agent_id must land in its bound thread; contents: {contents}"
    )




def test_directive_relay_folded_into_chain_drive_not_solo() -> None:
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    conductor_uuid = str(uuid.uuid4())
    drive = _build_ch_chain_drive(
        run_id="run-131c",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id=conductor_uuid,
        job_id="job-131c",
    )
    assert _CONDUCTOR_MARKER in drive, "the relay section header must live in CH_CHAIN_DRIVE after the fold"
    assert _INBOX_POLL_MARKER in drive, "CH_CHAIN_DRIVE must reference get_thread_history (the directive inbox poll)"
    assert _INBOX_POLL_CURSOR_MARKER in drive, "CH_CHAIN_DRIVE must use the unread_only Hub cursor for the inbox poll"
    assert "receive_messages" not in drive, "receive_messages is retired (bus hard-removed); the Hub is the poll now"
    assert conductor_uuid in drive, "CH_CHAIN_DRIVE must embed the conductor's agent_id (self-contained address)"

    solo = _build_orchestrator_protocol(
        cli_mode=True,
        project_id="proj-abc",
        orchestrator_id="job-abc",
        tenant_key="tk_test",
        include_implementation_reference=False,
    )
    assert "ch_conductor" not in solo, "the standalone ch_conductor chapter is removed (folded into CH_CHAIN_DRIVE)"
    assert "ch_chain_drive" not in solo, "a solo orchestrator (no chain_ctx) renders no drive chapter"
    assert _CONDUCTOR_MARKER not in str(solo), "a solo orchestrator must not see the conductor directive-relay prose"




def test_ch_conductor_chapter_content() -> None:
    test_agent_id = "conductor-agent-uuid-test"
    test_job_id = "conductor-job-uuid-test"

    ch = _build_ch_chain_drive(
        run_id="run-131c",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id=test_agent_id,
        job_id=test_job_id,
    )

    assert _CONDUCTOR_MARKER in ch, "Chapter must carry the folded directive-relay section header"
    assert test_agent_id in ch, "Chapter must embed the conductor agent_id"
    assert test_job_id in ch, "Chapter must embed the conductor job_id"
    assert _INBOX_POLL_MARKER in ch, "Chapter must instruct get_thread_history (inbox poll)"
    assert "receive_messages" not in ch, "receive_messages is retired (bus hard-removed)"
    assert "DIRECTIVE RELAY" in ch, "Chapter must include the directive relay protocol"
    assert "set_agent_status" in ch, "Chapter must reference set_agent_status (park-loop sleep step)"
    assert "get_my_turn" in ch, "Chapter must reference get_my_turn (baton check, existing park-loop step)"
    assert "NO WORKER-PROTOCOL FORK" in ch, "Chapter must carry the no-worker-protocol-fork mandate"




def test_worker_protocol_never_calls_pass_baton_or_writes_comm_threads_directly() -> None:
    from giljo_mcp.services.protocol_builder import _generate_agent_protocol

    modes = ["multi_terminal", "claude_code_cli", "codex_cli", "gemini_cli"]

    for mode in modes:
        protocol = _generate_agent_protocol(
            job_id="pin-job-id",
            tenant_key="tk_pin",
            agent_name="implementer",
            agent_id="pin-agent-id",
            execution_mode=mode,
            job_type="agent",
        )
        for forbidden in _FORBIDDEN_WORKER_CALLS:
            assert forbidden not in protocol, (
                f"Worker protocol for execution_mode={mode!r} must NOT mention "
                f"{forbidden!r}. Workers never call set_next_actor or write comm_threads "
                f"directly (Appendix A2 / A3 mandate; BE-6131c pin)."
            )
        assert "post_to_thread" in protocol, (
            f"Worker protocol for execution_mode={mode!r} must reference post_to_thread "
            f"(BE-9012d: the Hub replaced the bus for worker BLOCKER/HANDOVER/REQUEST_CONTEXT reporting)."
        )
        for retired in ("send_message(", "receive_messages(", "get_messages("):
            assert retired not in protocol, (
                f"Worker protocol for execution_mode={mode!r} must NOT reference the retired bus call {retired!r}."
            )
