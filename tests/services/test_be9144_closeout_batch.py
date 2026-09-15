# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


class _StatementCounter:
    def __init__(self, engine):
        self._engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def count(self, needle: str) -> int:
        upper = needle.upper()
        return sum(1 for s in self.statements if upper in s.upper())


async def _add_agent(db_session, tenant_key, project_id, status, *, todos=(), job_id=None):
    job_id = job_id or str(uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            job_type="implementer",
            mission="m",
            status="active",
            created_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="impl",
        status=status,
    )
    db_session.add(execution)
    await db_session.flush()
    for seq, (content, todo_status) in enumerate(todos):
        db_session.add(
            AgentTodoItem(
                job_id=job_id,
                tenant_key=tenant_key,
                content=content,
                status=todo_status,
                sequence=seq,
            )
        )
    await db_session.flush()
    return job_id, execution.id


@pytest_asyncio.fixture
async def seeded_project(db_session, test_tenant_key):
    product = Product(
        id=str(uuid4()),
        name=f"CO {uuid4().hex[:6]}",
        description="be9144 closeout batch",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid4()),
        tenant_key=test_tenant_key,
        product_id=product.id,
        name="P",
        description="d",
        mission="m",
        status="active",
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


def _service():
    return ProjectCloseoutService(None, TenantManager())


async def test_todos_read_in_one_query_and_report_matches(db_session, db_manager, test_tenant_key, seeded_project):
    project_id = seeded_project
    await _add_agent(
        db_session,
        test_tenant_key,
        project_id,
        "working",
        todos=[("A pending", "pending"), ("A running", "in_progress"), ("A done", "completed")],
        job_id="job-a",
    )
    await _add_agent(
        db_session,
        test_tenant_key,
        project_id,
        "working",
        todos=[("B pending", "pending")],
        job_id="job-b",
    )
    await _add_agent(
        db_session, test_tenant_key, project_id, "decommissioned", todos=[("C x", "pending")], job_id="job-c"
    )
    await _add_agent(
        db_session, test_tenant_key, project_id, "working", todos=[("orch todo", "pending")], job_id="job-orch"
    )

    svc = _service()
    engine = db_manager.async_engine.sync_engine
    with _StatementCounter(engine) as counter, tenant_session_context(db_session, test_tenant_key):
        report = await svc.evaluate_closeout_readiness(
            db_session, project_id, test_tenant_key, orchestrator_job_id="job-orch"
        )

    assert counter.count("FROM agent_todo_items") == 1, counter.statements

    assert report.agents_checked == 2
    by_job = {f.job_id: f for f in report.findings}
    assert set(by_job) == {"job-a", "job-b"}

    a = by_job["job-a"]
    assert sorted(a.incomplete_todos) == ["A pending", "A running"]
    assert a.incomplete_pending == 1
    assert a.incomplete_in_progress == 1

    b = by_job["job-b"]
    assert b.incomplete_todos == ["B pending"]
    assert b.incomplete_pending == 1

    assert report.orchestrator_incomplete == ["orch todo"]
    assert report.orchestrator_pending == 1
    assert report.orchestrator_in_progress == 0


async def test_pending_approvals_read_in_one_query(db_session, db_manager, test_tenant_key, seeded_project):
    project_id = seeded_project
    _, exec_d = await _add_agent(db_session, test_tenant_key, project_id, "awaiting_user", job_id="job-d")
    _, exec_e = await _add_agent(db_session, test_tenant_key, project_id, "awaiting_user", job_id="job-e")

    approvals = {}
    for exec_id, job_id in ((exec_d, "job-d"), (exec_e, "job-e")):
        approval = UserApproval(
            tenant_key=test_tenant_key,
            agent_execution_id=exec_id,
            job_id=job_id,
            project_id=project_id,
            reason="r",
            options=[{"id": "a", "label": "A"}],
            context=None,
            status="pending",
        )
        db_session.add(approval)
        approvals[job_id] = approval
    await db_session.flush()
    expected = {job_id: appr.id for job_id, appr in approvals.items()}

    svc = _service()
    engine = db_manager.async_engine.sync_engine
    with _StatementCounter(engine) as counter, tenant_session_context(db_session, test_tenant_key):
        report = await svc.evaluate_closeout_readiness(db_session, project_id, test_tenant_key)

    assert counter.count("FROM user_approvals") == 1, counter.statements

    resolved = {f.job_id: f.approval_id for f in report.findings}
    assert resolved == expected
    assert all(f.awaiting_user for f in report.findings)
