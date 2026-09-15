# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


@pytest_asyncio.fixture(autouse=True)
async def _wipe_sequence_runs(db_manager):
    yield
    async with db_manager.get_session_async() as session:
        with tenant_isolation_bypass(
            session, reason="test teardown: wipe sequence_runs (per-worker DB)", models=(SequenceRun,)
        ):
            await session.execute(delete(SequenceRun))
        await session.commit()


async def _seed_project(session: AsyncSession, tenant_key: str) -> str:
    project_id = str(uuid.uuid4())
    _product_id = str(uuid.uuid4())
    session.add(
        Product(
            id=_product_id,
            tenant_key=tenant_key,
            name=f"Owning Product {_product_id[:8]}",
            description="seeded",
            is_active=False,
        )
    )
    session.add(
        Project(
            id=project_id,
            product_id=_product_id,
            tenant_key=tenant_key,
            name=f"BE-6131g {project_id[:8]}",
            description="conductor directive test",
            mission="Drive sequential run as conductor.",
            status="active",
            execution_mode=_MODE,
            series_number=next_series_number(),
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project_id


async def _spawn_orchestrator(session: AsyncSession, tenant_key: str, project_id: str) -> str:
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
    return str(row.scalar_one().agent_id)


async def _post_directive(
    session: AsyncSession,
    tenant_key: str,
    *,
    project_id: str | None,
    to_agent: str,
    content: str,
) -> Message:
    thread = CommThread(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        serial=random.randint(1, 90000),
        subject="chain directive test thread",
        status="open",
        project_id=project_id,
    )
    session.add(thread)
    await session.flush()
    msg = Message(
        tenant_key=tenant_key,
        project_id=project_id,
        thread_id=thread.id,
        from_agent_id=f"user:{uuid.uuid4().hex[:8]}",
        content=content,
        status="pending",
        requires_action=True,
        created_at=datetime.now(UTC),
    )
    session.add(msg)
    await session.flush()
    session.add(MessageRecipient(message_id=msg.id, agent_id=to_agent, tenant_key=tenant_key))
    await session.commit()
    await session.refresh(msg)
    return msg




async def test_chain_directive_single_recipient_no_fanout(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    head_pid = await _seed_project(db_session, tenant)
    sub_pid = await _seed_project(db_session, tenant)
    conductor_id = await _spawn_orchestrator(db_session, tenant, head_pid)
    sub_orchestrator_id = await _spawn_orchestrator(db_session, tenant, sub_pid)

    msg = await _post_directive(
        db_session,
        tenant,
        project_id=head_pid,
        to_agent=conductor_id,
        content="DIRECTIVE: pause after project 2 and confirm.",
    )

    recipient_rows = (
        (
            await db_session.execute(
                select(MessageRecipient.agent_id).where(
                    MessageRecipient.message_id == msg.id,
                    MessageRecipient.tenant_key == tenant,
                )
            )
        )
        .scalars()
        .all()
    )
    assert recipient_rows == [conductor_id], (
        f"a Hub chain directive must target ONLY the conductor; got {recipient_rows}"
    )
    assert sub_orchestrator_id not in recipient_rows, (
        "FAN-OUT LEAK: a sub-orchestrator received a conductor-only directive"
    )




async def test_steering_targets_dedicated_conductor(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    head_pid = await _seed_project(db_session, tenant)
    sub_pid = await _seed_project(db_session, tenant)

    svc = SequenceRunService(db_manager=None, tenant_manager=None, session=db_session)
    run = await svc.create(
        project_ids=[head_pid, sub_pid],
        resolved_order=[head_pid, sub_pid],
        execution_mode=_MODE,
        status="running",
        project_statuses={head_pid: "implementing", sub_pid: "pending"},
        tenant_key=tenant,
    )
    run_id = run["id"]
    conductor_agent_id = run["conductor_agent_id"]
    assert conductor_agent_id is not None

    head_orch = await _spawn_orchestrator(db_session, tenant, head_pid)
    resolver = SequenceChainContextResolver(
        db_manager=None, tenant_manager=TenantManager(), websocket_manager=None, test_session=db_session
    )
    head_ctx = await resolver.resolve(
        db_session, project_id=head_pid, tenant_key=tenant, orchestrator_agent_id=head_orch, is_staging=False
    )
    assert head_ctx is not None and head_ctx.role == "sub_orchestrator"

    refreshed = await svc.get(run_id=run_id, tenant_key=tenant)
    assert refreshed["conductor_agent_id"] == conductor_agent_id, "the conductor identity must be stable"

    msg = await _post_directive(
        db_session,
        tenant,
        project_id=None,
        to_agent=refreshed["conductor_agent_id"],
        content="DIRECTIVE: after restart, skip project 2.",
    )
    recipients = (
        (
            await db_session.execute(
                select(MessageRecipient.agent_id).where(
                    MessageRecipient.message_id == msg.id,
                    MessageRecipient.tenant_key == tenant,
                )
            )
        )
        .scalars()
        .all()
    )
    assert recipients == [conductor_agent_id], (
        f"a directive to the run's conductor must target ONLY the dedicated conductor; got {recipients}"
    )
    assert head_orch not in recipients, "the head project's own sub-orchestrator must never receive the directive"




async def test_chain_directive_lives_on_a_hub_thread(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    head_pid = await _seed_project(db_session, tenant)
    conductor_id = await _spawn_orchestrator(db_session, tenant, head_pid)
    msg = await _post_directive(
        db_session, tenant, project_id=head_pid, to_agent=conductor_id, content="DIRECTIVE: hold."
    )

    threaded = (
        await db_session.execute(
            select(func.count()).select_from(Message).where(Message.id == msg.id, Message.thread_id.isnot(None))
        )
    ).scalar()
    assert threaded == 1, "a chain directive must be a Hub thread post (thread_id NOT NULL) post-migration"
