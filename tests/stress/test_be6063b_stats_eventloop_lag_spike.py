# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6063b spike: where does the dashboard /stats hot path actually stall?

The project premise was "the whole app runs SYNCHRONOUS SQLAlchemy; every
``await session.execute()`` blocks the loop." Static analysis refutes that for
the request/MCP hot paths (the API process builds ``DatabaseManager(is_async=True)``
and every tool/service uses ``get_session_async`` -> asyncpg). This module
MEASURES the real culprit instead of assuming it.

It reproduces the ``/stats/projects`` access pattern two ways against the same
seeded tenant while a background coroutine samples event-loop scheduling lag:

  * ``_load_via_n_plus_one``    — today's endpoint: 1 page query + N*5 separate
    ``get_session_async`` round-trips (one fresh session per per-project count).
  * ``_load_via_single_session`` — the BE-6063b fix shape: ONE session, set-based
    aggregate join collapsing the per-project counts into a single round-trip.

The asserts pin two behaviours so a future regression is caught:

  1. The N+1 path issues O(N) sessions and the set-based path issues O(1) — this
     is the round-trip-collapse guarantee, the thing that actually matters on the
     single sync worker (pool-checkout pressure, not a hard loop block).
  2. Event-loop lag stays bounded on BOTH paths — i.e. the awaited asyncpg calls
     do NOT hard-block the loop. This is the evidence that the symptom is
     latency / connection-checkout pressure, not a synchronous stall.

Markers: ``stress`` (perf characterisation) + ``integration`` (real DB).
Parallel-safe: unique tenant per run, committed rows cleaned up in teardown,
no module-level mutable state.
"""

import asyncio
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Message, Product, Project, Task
from giljo_mcp.repositories.product_statistics_repository import ProductStatisticsRepository


pytestmark = [pytest.mark.stress, pytest.mark.integration]

SEED_PROJECT_COUNT = 12
MESSAGES_PER_PROJECT = 4
TASKS_PER_PROJECT = 3
CONCURRENT_REQUESTS = 8


class _LoopLagSampler:
    """Background coroutine sampling event-loop scheduling drift.

    Schedules itself every ``interval`` seconds; the gap between the intended
    wake time and the actual wake time is loop lag. A hard synchronous block on
    the loop shows up as a large max-lag spike; cooperative await points do not.
    """

    def __init__(self, interval: float = 0.005):
        self._interval = interval
        self._running = False
        self._task: asyncio.Task | None = None
        self.samples: list[float] = []

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        expected = loop.time() + self._interval
        while self._running:
            await asyncio.sleep(self._interval)
            now = loop.time()
            self.samples.append(max(0.0, now - expected))
            expected = now + self._interval

    def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    @property
    def max_lag(self) -> float:
        return max(self.samples) if self.samples else 0.0


@pytest_asyncio.fixture
async def seeded_tenant(db_manager):
    """Seed a unique tenant with N projects + children via COMMITTED sessions.

    Committed (not rolled back) because the N+1 path under test opens its own
    fresh sessions that must observe the rows. Cleaned up in teardown.
    """
    tenant_key = f"tk_spike_{uuid4().hex[:12]}"
    project_ids: list[str] = []

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            product = Product(tenant_key=tenant_key, name="spike", description="seed", is_active=True)
            session.add(product)
            await session.flush()
            for i in range(SEED_PROJECT_COUNT):
                # BE-9437: a project belongs to a product. Its own, so an active
                # seed cannot collide under idx_project_single_active_per_product.
                _owning_product_project = Product(
                    id=str(uuid4()),
                    tenant_key=tenant_key,
                    name=f"Owning Product {uuid4().hex[:6]}",
                    description="seeded",
                    is_active=False,
                )
                session.add(_owning_product_project)
                project = Project(
                    tenant_key=tenant_key,
                    product_id=_owning_product_project.id,
                    name=f"spike-{i}",
                    description="be6063b spike seed",
                    mission="seed",
                    status="active",
                    series_number=(uuid4().int % (10**9)),
                )
                session.add(project)
                await session.flush()
                project_ids.append(str(project.id))

                job = AgentJob(
                    job_id=str(uuid4()),
                    tenant_key=tenant_key,
                    project_id=project.id,
                    mission="seed",
                    job_type="implementer",
                    status="active",
                )
                session.add(job)
                session.add(
                    AgentExecution(
                        job_id=job.job_id,
                        agent_id=str(uuid4()),
                        tenant_key=tenant_key,
                        agent_display_name="impl",
                        agent_name=f"impl-{i}",
                        status="working",
                    )
                )
                for _ in range(MESSAGES_PER_PROJECT):
                    session.add(Message(tenant_key=tenant_key, project_id=project.id, content="x", status="pending"))
                for t in range(TASKS_PER_PROJECT):
                    session.add(
                        Task(
                            tenant_key=tenant_key,
                            product_id=product.id,
                            project_id=project.id,
                            title=f"task-{t}",
                            status="completed" if t == 0 else "pending",
                        )
                    )

    yield tenant_key, project_ids

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(delete(Message).where(Message.tenant_key == tenant_key))
            await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
            await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
            await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
            await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))


async def _count_messages(db_manager, tenant_key, project_id):
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            return await session.scalar(
                select(func.count(Message.id)).where(Message.project_id == project_id, Message.tenant_key == tenant_key)
            )


async def _load_via_n_plus_one(db_manager, tenant_key) -> tuple[int, int]:
    """Today's pattern: page query + one fresh session per per-project count.

    Returns (rows, session_count) where session_count is the number of distinct
    ``get_session_async`` round-trips this path issued.
    """
    session_count = 0
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session_count += 1
        with tenant_session_context(session, tenant_key):
            projects = list(
                (await session.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
            )
    rows = 0
    for project in projects:
        # Mirror the 5 per-project round-trips of the real endpoint with fresh sessions.
        for _ in range(5):
            await _count_messages(db_manager, tenant_key, project.id)
            session_count += 1
        rows += 1
    return rows, session_count


async def _load_via_single_session(db_manager, tenant_key) -> tuple[int, int]:
    """Fix shape: the real BE-6063b production method — ONE session, set-based."""
    repo = ProductStatisticsRepository(db_manager)
    session_count = 0
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session_count += 1
        with tenant_session_context(session, tenant_key):
            rows = await repo.get_project_stats_aggregated(session, tenant_key, limit=1000)
    return len(rows), session_count


async def _run_concurrent(loader, db_manager, tenant_key):
    sampler = _LoopLagSampler()
    sampler.start()
    start = time.perf_counter()
    results = await asyncio.gather(*[loader(db_manager, tenant_key) for _ in range(CONCURRENT_REQUESTS)])
    elapsed = time.perf_counter() - start
    await sampler.stop()
    total_sessions = sum(r[1] for r in results)
    return elapsed, sampler.max_lag, total_sessions


@pytest.mark.asyncio
async def test_set_based_aggregate_counts_project_linked_children(seeded_tenant, db_manager):
    """Correctness: the real aggregate counts project-linked messages/tasks/agents.

    Unlike the service-test seed (product-scoped tasks), this seed links every
    child to its project, so the task/completed subqueries must return non-zero —
    proving those correlated subqueries are live, not silently zero.
    """
    tenant_key, _ = seeded_tenant
    repo = ProductStatisticsRepository(db_manager)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            rows = await repo.get_project_stats_aggregated(session, tenant_key, limit=1000)

    assert len(rows) == SEED_PROJECT_COUNT
    for _project, agent_count, message_count, task_count, completed_count, last_activity in rows:
        assert agent_count == 1
        assert message_count == MESSAGES_PER_PROJECT
        assert task_count == TASKS_PER_PROJECT
        assert completed_count == 1  # exactly one completed task per project (t == 0)
        assert last_activity is not None


@pytest.mark.asyncio
async def test_n_plus_one_issues_o_n_sessions_set_based_issues_o_1(seeded_tenant, db_manager):
    """Round-trip collapse: N+1 path opens O(N) sessions, set-based opens O(1)."""
    tenant_key, _ = seeded_tenant

    _, _, n1_sessions = await _run_concurrent(_load_via_n_plus_one, db_manager, tenant_key)
    _, _, set_sessions = await _run_concurrent(_load_via_single_session, db_manager, tenant_key)

    expected_n1 = CONCURRENT_REQUESTS * (1 + SEED_PROJECT_COUNT * 5)
    assert n1_sessions == expected_n1, f"N+1 path session count drifted: {n1_sessions} != {expected_n1}"
    assert set_sessions == CONCURRENT_REQUESTS, (
        f"set-based path must open exactly one session per request, got {set_sessions}"
    )
    # The collapse is the whole point: set-based path uses a tiny fraction of sessions.
    assert set_sessions * 10 < n1_sessions


@pytest.mark.asyncio
async def test_async_stats_paths_do_not_hard_block_the_loop(seeded_tenant, db_manager):
    """Evidence the symptom is latency/checkout pressure, NOT a synchronous stall.

    Both the N+1 and the set-based path await asyncpg between every round-trip, so
    neither should hard-block the event loop. A regression that drops a sync
    psycopg2 call (or a CPU-bound serialize) onto the loop would spike max_lag.
    The threshold is generous (loop lag, not wall-clock latency) on purpose.
    """
    tenant_key, _ = seeded_tenant

    _, n1_lag, _ = await _run_concurrent(_load_via_n_plus_one, db_manager, tenant_key)
    _, set_lag, _ = await _run_concurrent(_load_via_single_session, db_manager, tenant_key)

    assert n1_lag < 1.0, f"N+1 path hard-blocked the loop (max lag {n1_lag:.3f}s) — premise would be confirmed"
    assert set_lag < 1.0, f"set-based path hard-blocked the loop (max lag {set_lag:.3f}s)"
