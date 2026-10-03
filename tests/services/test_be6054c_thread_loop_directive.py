# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager

from tests.unit.test_be6008_staged_agent_mailboxes import (
    _get_execution,
    _seed_project,
    _seed_template,
)


pytestmark = pytest.mark.asyncio

_DIRECTIVE_MARKER = "LOOP / SLEEP DIRECTIVE"


def _comm(db_session) -> CommThreadService:
    return CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)


async def _seed_cht(db_session, tenant_key: str) -> None:
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)


async def _spawn_agent(db_session: AsyncSession, tenant_key: str) -> tuple[str, str]:
    project_id = await _seed_project(
        db_session, tenant_key, execution_mode="multi_terminal", implementation_launched=True
    )
    await _seed_template(db_session, tenant_key, "implementer")
    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    result = await lifecycle.spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Implement the feature.",
    )
    execution = await _get_execution(db_session, tenant_key, result.job_id)
    return result.job_id, str(execution.agent_id)


async def _fetch_protocol(
    db_session: AsyncSession, tenant_key: str, job_id: str, preset_name: str | None = None
) -> str:
    mission_service = MissionService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    response = await mission_service.get_agent_mission(job_id=job_id, tenant_key=tenant_key, preset_name=preset_name)
    return response.full_protocol or ""




async def test_has_active_loop_directive_true_when_armed(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    thread = await comm.create_thread(subject="loop me", creator_id="agent-x", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="please loop until resolved",
        to_participant="agent-x",
        loop_directive=True,
        user_id=None,
        from_agent="orchestrator",
        tenant_key=tenant,
    )
    assert await comm.has_active_loop_directive(agent_id="agent-x", tenant_key=tenant) is True


async def test_has_active_loop_directive_false_after_thread_closed(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    thread = await comm.create_thread(subject="loop me", creator_id="agent-x", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop",
        to_participant="agent-x",
        loop_directive=True,
        from_agent="orchestrator",
        tenant_key=tenant,
    )
    assert await comm.has_active_loop_directive(agent_id="agent-x", tenant_key=tenant) is True

    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="done",
        from_agent="orchestrator",
        set_status="closed",
        tenant_key=tenant,
    )
    assert await comm.has_active_loop_directive(agent_id="agent-x", tenant_key=tenant) is False


async def test_has_active_loop_directive_false_when_not_armed(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    thread = await comm.create_thread(subject="quiet", creator_id="agent-x", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="hi",
        to_participant="agent-x",
        from_agent="orchestrator",
        tenant_key=tenant,
    )
    assert await comm.has_active_loop_directive(agent_id="agent-x", tenant_key=tenant) is False




async def test_directive_injected_into_mission_when_armed(db_session):
    tenant = TenantManager.generate_tenant_key()
    job_id, agent_id = await _spawn_agent(db_session, tenant)
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    thread = await comm.create_thread(subject="loop", creator_id="orchestrator", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop until resolved",
        to_participant=agent_id,
        loop_directive=True,
        from_agent="orchestrator",
        tenant_key=tenant,
    )
    protocol = await _fetch_protocol(db_session, tenant, job_id)
    assert _DIRECTIVE_MARKER in protocol


async def test_directive_absent_when_not_armed(db_session):
    tenant = TenantManager.generate_tenant_key()
    job_id, _agent_id = await _spawn_agent(db_session, tenant)
    protocol = await _fetch_protocol(db_session, tenant, job_id)
    assert _DIRECTIVE_MARKER not in protocol


async def test_directive_absent_after_thread_closed(db_session):
    tenant = TenantManager.generate_tenant_key()
    job_id, agent_id = await _spawn_agent(db_session, tenant)
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    thread = await comm.create_thread(subject="loop", creator_id="orchestrator", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop",
        to_participant=agent_id,
        loop_directive=True,
        from_agent="orchestrator",
        tenant_key=tenant,
    )
    assert _DIRECTIVE_MARKER in await _fetch_protocol(db_session, tenant, job_id)

    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="resolved",
        from_agent="orchestrator",
        set_status="closed",
        tenant_key=tenant,
    )
    assert _DIRECTIVE_MARKER not in await _fetch_protocol(db_session, tenant, job_id)


_SHELL_SLEEP = ("sleep 1 N", "Start-Sleep", "sleep-and-check", "shell sleep")


async def _armed_directive(db_session, preset_name: str | None) -> str:
    tenant = TenantManager.generate_tenant_key()
    job_id, agent_id = await _spawn_agent(db_session, tenant)
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)
    thread = await comm.create_thread(subject="loop", creator_id="orchestrator", tenant_key=tenant)
    await comm.post_to_thread(
        thread_id=thread["thread_id"],
        content="loop until resolved",
        to_participant=agent_id,
        loop_directive=True,
        from_agent="orchestrator",
        tenant_key=tenant,
    )
    protocol = await _fetch_protocol(db_session, tenant, job_id, preset_name)
    assert _DIRECTIVE_MARKER in protocol
    return protocol[protocol.index(_DIRECTIVE_MARKER) :]


@pytest.mark.parametrize("preset_name", ["desktop_app", "web_sandbox", "chat"])
async def test_directive_on_a_shell_less_preset_orders_no_shell_sleep(db_session, preset_name):
    directive = await _armed_directive(db_session, preset_name)
    leaked = [marker for marker in _SHELL_SLEEP if marker in directive]
    assert not leaked, f"loop directive[{preset_name}] leaked {leaked}"
    assert "`get_my_turn(agent_id=<you>)`" in directive
    assert "TERMINATION (do not loop forever)" in directive


async def test_directive_without_a_preset_keeps_the_shell_sleep(db_session):
    directive = await _armed_directive(db_session, None)
    for marker in _SHELL_SLEEP:
        assert marker in directive, f"CLI loop directive lost {marker!r}"
