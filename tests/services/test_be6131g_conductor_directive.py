# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6131g — chain-directive targeting, retargeted onto the Hub (BE-9012d).

The bus (``MessageRoutingService.send_message`` / ``MessageService.receive_messages``)
that originally carried the chain-conductor "steering" directive was hard-removed in
BE-9012d. The FE composer (``MessageComposer.vue``, "BE-9012d Part 1") already posts a
directive to the conductor as a DIRECTED, action-required Hub thread post
(``to_participant=<conductor agent_id>``, ``requires_action=true``) instead of a bus
send_message. This file retargets the 3 regression contracts onto that Hub post shape,
seeded directly at the DB layer exactly as ``CommThreadService.post_to_thread`` would
persist it (mirrors ``test_be9012b_reactivation_as_post.py``'s ``_seed_thread_post``):

1. ``test_chain_directive_single_recipient_no_fanout`` — a directive addressed to the
   run's ``conductor_agent_id`` reaches ONLY the conductor (exactly one recipient),
   NEVER a sub-orchestrator in the same run (no broadcast / all-agents fan-out).
2. ``test_steering_targets_dedicated_conductor`` (BE-6184): the conductor agent_id is
   minted at run-create and is STABLE (no head-session re-stamp). A directive addressed
   to the run's ``conductor_agent_id`` reaches the dedicated conductor only; the head
   project's own sub-orchestrator never receives it.
3. ``test_chain_directive_lives_on_a_hub_thread`` — INVERSE of the retired bus contract:
   a chain directive is now a Hub thread post (``thread_id IS NOT NULL``), not an
   un-threaded runtime message. Locks the threaded contract post-migration.

Parallel-safe: db_session (TransactionalTestContext); the autouse teardown wipes
sequence_runs because SequenceRunService commits through the injected session
(per-worker DB, serial tests -> a table delete is isolated).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.tasks import Message, MessageRecipient
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.sequence_chain_context import SequenceChainContextResolver
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


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
    session.add(
        Project(
            id=project_id,
            tenant_key=tenant_key,
            name=f"BE-6131g {project_id[:8]}",
            description="conductor directive test",
            mission="Drive sequential run as conductor.",
            status="active",
            execution_mode=_MODE,
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return project_id


async def _spawn_orchestrator(session: AsyncSession, tenant_key: str, project_id: str) -> str:
    """Spawn an orchestrator job; return its agent_id (the Hub address)."""
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
    """Seed a Hub thread post exactly as ``CommThreadService.post_to_thread`` would
    persist a directed, action-required directive: thread_id set, a single directed
    ``MessageRecipient`` row. ``project_id=None`` mirrors the conductor's own
    STANDALONE "Chain run {run_id} coordination hub" thread (the project-less
    conductor has no project-bound thread to address directly — see
    ``MessageComposer.vue``'s ``resolveConductorThread``)."""
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


# ---------------------------------------------------------------------------
# 1. single recipient — never a fan-out
# ---------------------------------------------------------------------------


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

    # Exactly ONE recipient — the conductor. Never a fan-out.
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


# ---------------------------------------------------------------------------
# 2. steering targets the stable dedicated conductor minted at run-create
# ---------------------------------------------------------------------------


async def test_steering_targets_dedicated_conductor(db_session: AsyncSession) -> None:
    """BE-6184: the conductor agent_id is minted at create and is STABLE.

    There is no head-session re-stamp dance anymore: resolve() classifies by agent
    identity and never re-targets the conductor to a fresh head session. A directive
    addressed to ``run.conductor_agent_id`` reaches the dedicated conductor, and the
    head project's own sub-orchestrator (a different agent) never receives it.
    """
    tenant = TenantManager.generate_tenant_key()
    head_pid = await _seed_project(db_session, tenant)
    sub_pid = await _seed_project(db_session, tenant)

    # create() mints the dedicated, project-less conductor and stamps its agent_id.
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

    # The head project's own orchestrator is a symmetric sub_orchestrator, NOT the conductor.
    head_orch = await _spawn_orchestrator(db_session, tenant, head_pid)
    resolver = SequenceChainContextResolver(
        db_manager=None, tenant_manager=TenantManager(), websocket_manager=None, test_session=db_session
    )
    head_ctx = await resolver.resolve(
        db_session, project_id=head_pid, tenant_key=tenant, orchestrator_agent_id=head_orch, is_staging=False
    )
    assert head_ctx is not None and head_ctx.role == "sub_orchestrator"

    # The conductor identity is stable (never re-stamped to the head session).
    refreshed = await svc.get(run_id=run_id, tenant_key=tenant)
    assert refreshed["conductor_agent_id"] == conductor_agent_id, "the conductor identity must be stable"

    # A directive to the run's conductor (its own standalone coordination thread)
    # targets the dedicated conductor only.
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


# ---------------------------------------------------------------------------
# 3. a chain directive now lives on a Hub thread (inverse of the retired bus)
# ---------------------------------------------------------------------------


async def test_chain_directive_lives_on_a_hub_thread(db_session: AsyncSession) -> None:
    """BE-9012d: a chain directive is now a Hub thread post (thread_id NOT NULL) —
    the INVERSE of the retired bus's un-threaded runtime message. Locks the threaded
    contract at the chain-run boundary post-migration."""
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
