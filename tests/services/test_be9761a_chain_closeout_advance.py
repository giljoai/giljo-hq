# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import TENANT_CONTEXT_SOURCE_KEY
from giljo_mcp.models import Product, Project
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.services.project_helpers import broadcast_deferred_events, mark_chain_member_status
from giljo_mcp.services.sequence_chain_context import chain_member_phase, resolve_chain_launch_gate
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.project_closeout import close_project_and_update_memory


pytestmark = pytest.mark.asyncio


class _RecordingWS:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def broadcast_event_to_tenant(self, tenant_key: str, event: dict) -> None:
        self.events.append(("event", event))

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))

    async def broadcast_project_update(self, **kwargs) -> None:
        self.events.append(("project_update", kwargs))


async def _seed_member(session: AsyncSession, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"BE-9761a {uuid.uuid4().hex[:6]}",
        description="Chain product.",
        tenant_key=tenant_key,
        is_active=False,
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"BE-9761a member {uuid.uuid4().hex[:6]}",
        description="Chain member.",
        mission="Be a chain member.",
        status="inactive",
        staging_status="staged",
        tenant_key=tenant_key,
        product_id=product.id,
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    session.add(project)
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project.id


async def _seed_running_chain(session: AsyncSession, tenant_key: str, size: int = 3) -> tuple[str, list[str]]:
    members = [await _seed_member(session, tenant_key) for _ in range(size)]
    run = await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session).create(
        project_ids=members,
        resolved_order=members,
        execution_mode="claude_code_cli",
        status="running",
        project_statuses=dict.fromkeys(members, "pending") | {members[0]: "implementing"},
        tenant_key=tenant_key,
    )
    head = await _project(session, tenant_key, members[0])
    head.implementation_launched_at = datetime.now(UTC)
    head.staging_status = "staging_complete"
    head.status = "active"
    await session.flush()
    return run["id"], members


async def _project(session: AsyncSession, tenant_key: str, project_id: str) -> Project:
    row = (
        await session.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one()
    await session.refresh(row)
    return row


async def _run(session: AsyncSession, tenant_key: str, run_id: str) -> dict:
    return await SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=session).get(
        run_id=run_id, tenant_key=tenant_key
    )


async def _close_via_mcp(session, tenant_key, project_id, ws) -> None:
    await close_project_and_update_memory(
        project_id=project_id,
        summary="done",
        key_outcomes=["x"],
        decisions_made=["y"],
        tenant_key=tenant_key,
        db_manager=object(),
        session=session,
        force=True,
        websocket_manager=ws,
    )
    await broadcast_deferred_events(session)


async def _close_via_rest(session, tenant_key, project_id, ws) -> None:
    await ProjectCloseoutService(None, TenantManager(), test_session=session, websocket_manager=ws).close_out_project(
        project_id=project_id, tenant_key=tenant_key
    )


CLOSEOUT_DOORS = pytest.mark.parametrize("close", [_close_via_mcp, _close_via_rest], ids=["mcp", "rest"])


@CLOSEOUT_DOORS
async def test_member_closeout_advances_run_and_opens_next_gate(db_session: AsyncSession, close) -> None:
    tenant = TenantManager.generate_tenant_key()
    run_id, (p1, p2, p3) = await _seed_running_chain(db_session, tenant)
    ws = _RecordingWS()

    await close(db_session, tenant, p1, ws)

    run = await _run(db_session, tenant, run_id)
    assert run["project_statuses"][p1] == "completed"
    assert run["current_index"] == 1, f"the run must advance to member 2 on member 1's closeout, got {run}"
    assert run["project_statuses"][p2] == "pending", "member 2 has not started; only its gate is open"

    second = await _project(db_session, tenant, p2)
    assert second.implementation_launched_at is not None, "member 2's gate must open so its play shows"
    assert second.status == "active", "an opened member is shown on the Jobs board like a launched solo project"
    assert second.staging_status == "staged", "opening the gate must not fake the member's staging"
    assert chain_member_phase(second) == "staging", "member 2's prompt still starts at staging"
    _member, blocker = await resolve_chain_launch_gate(db_session, project_id=p2, tenant_key=tenant)
    assert blocker is None

    third = await _project(db_session, tenant, p3)
    assert third.implementation_launched_at is None, "only the NEXT member opens"

    launched = [data for kind, data in ws.events if kind == "project:implementation_launched"]
    assert [d["project_id"] for d in launched] == [p2], f"the dashboard must hear member 2 open, got {ws.events}"


async def test_last_member_closeout_keeps_index_in_range(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    run_id, (p1, p2) = await _seed_running_chain(db_session, tenant, size=2)
    await _close_via_mcp(db_session, tenant, p1, None)
    await _close_via_mcp(db_session, tenant, p2, None)

    run = await _run(db_session, tenant, run_id)
    assert run["current_index"] == 1, "the last member's closeout has no next member to advance to"
    assert run["project_statuses"] == {p1: "completed", p2: "completed"}


async def test_closeout_never_reopens_an_already_open_next_gate(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    _run_id, (p1, p2, _p3) = await _seed_running_chain(db_session, tenant)
    second = await _project(db_session, tenant, p2)
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    second.implementation_launched_at = earlier
    await db_session.flush()

    await _close_via_mcp(db_session, tenant, p1, None)

    second = await _project(db_session, tenant, p2)
    assert second.implementation_launched_at == earlier


async def test_solo_closeout_touches_no_run(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    solo = await _seed_member(db_session, tenant)
    other_run_id, others = await _seed_running_chain(db_session, tenant, size=2)

    await _close_via_mcp(db_session, tenant, solo, None)

    run = await _run(db_session, tenant, other_run_id)
    assert run["current_index"] == 0
    assert (await _project(db_session, tenant, others[1])).implementation_launched_at is None


class _DistinctSessionManager:

    def __init__(self, connection) -> None:
        self._connection = connection
        self.sessions: list[AsyncSession] = []

    @asynccontextmanager
    async def get_session_async(self, tenant_key: str | None = None):
        session = AsyncSession(bind=self._connection, expire_on_commit=False)
        if tenant_key:
            session.info["tenant_key"] = tenant_key
            session.info[TENANT_CONTEXT_SOURCE_KEY] = "service"
        self.sessions.append(session)
        try:
            yield session
            await session.commit()
        finally:
            await session.close()


async def test_own_session_path_still_announces_the_opened_gate(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    _run_id, (p1, p2, _p3) = await _seed_running_chain(db_session, tenant)
    await db_session.commit()
    ws = _RecordingWS()
    manager = _DistinctSessionManager(await db_session.connection())

    await mark_chain_member_status(
        db_manager=manager,
        tenant_manager=TenantManager(),
        project_id=p1,
        tenant_key=tenant,
        status="completed",
        test_session=None,
        websocket_manager=ws,
    )

    assert len(manager.sessions) >= 2, "precondition: the helper ran on sessions of its own"
    assert (await _project(db_session, tenant, p2)).implementation_launched_at is not None
    launched = [data for kind, data in ws.events if kind == "project:implementation_launched"]
    assert [d["project_id"] for d in launched] == [p2], f"the opened gate must reach the dashboard, got {ws.events}"
