# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    tenant_key = f"tk_spike_{uuid4().hex[:12]}"
    project_ids: list[str] = []

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            product = Product(tenant_key=tenant_key, name="spike", description="seed", is_active=True)
            session.add(product)
            await session.flush()
            for i in range(SEED_PROJECT_COUNT):
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
    session_count = 0
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session_count += 1
        with tenant_session_context(session, tenant_key):
            projects = list(
                (await session.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
            )
    rows = 0
    for project in projects:
        for _ in range(5):
            await _count_messages(db_manager, tenant_key, project.id)
            session_count += 1
        rows += 1
    return rows, session_count


async def _load_via_single_session(db_manager, tenant_key) -> tuple[int, int]:
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
        assert completed_count == 1
        assert last_activity is not None


@pytest.mark.asyncio
async def test_n_plus_one_issues_o_n_sessions_set_based_issues_o_1(seeded_tenant, db_manager):
    tenant_key, _ = seeded_tenant

    _, _, n1_sessions = await _run_concurrent(_load_via_n_plus_one, db_manager, tenant_key)
    _, _, set_sessions = await _run_concurrent(_load_via_single_session, db_manager, tenant_key)

    expected_n1 = CONCURRENT_REQUESTS * (1 + SEED_PROJECT_COUNT * 5)
    assert n1_sessions == expected_n1, f"N+1 path session count drifted: {n1_sessions} != {expected_n1}"
    assert set_sessions == CONCURRENT_REQUESTS, (
        f"set-based path must open exactly one session per request, got {set_sessions}"
    )
    assert set_sessions * 10 < n1_sessions


@pytest.mark.asyncio
async def test_async_stats_paths_do_not_hard_block_the_loop(seeded_tenant, db_manager):
    tenant_key, _ = seeded_tenant

    _, n1_lag, _ = await _run_concurrent(_load_via_n_plus_one, db_manager, tenant_key)
    _, set_lag, _ = await _run_concurrent(_load_via_single_session, db_manager, tenant_key)

    assert n1_lag < 1.0, f"N+1 path hard-blocked the loop (max lag {n1_lag:.3f}s) — premise would be confirmed"
    assert set_lag < 1.0, f"set-based path hard-blocked the loop (max lag {set_lag:.3f}s)"
