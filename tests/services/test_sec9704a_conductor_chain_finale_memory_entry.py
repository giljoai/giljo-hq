# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob, AgentTodoItem
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.services.conductor_job_minter import mint_conductor_job
from giljo_mcp.services.protocol_sections import chapters_chain
from giljo_mcp.tools.write_memory_entry import write_360_memory


DRIVE_TODOS = ("Poll P1 for closeout", "Advance to P2", "Poll P2 for closeout", "Write the series summary")


@pytest.fixture(autouse=True)
def _stub_staleness():
    async def _noop(*args, **kwargs):
        return {"is_stale": False, "projects_since_tune": 0, "threshold": 3, "enabled": True}

    with patch(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        new=_noop,
    ):
        yield


async def _seed_job(db_session, tenant_key, project_id, job_type, execution_status, todos=()):
    job_id = str(uuid.uuid4())
    db_session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            job_type=job_type,
            mission=f"{job_type} mission",
            status="active",
        )
    )
    db_session.add(
        AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name=job_type,
            agent_name=job_type,
            status=execution_status,
            started_at=datetime.now(UTC),
        )
    )
    for sequence, (content, status) in enumerate(todos):
        db_session.add(
            AgentTodoItem(job_id=job_id, tenant_key=tenant_key, content=content, status=status, sequence=sequence)
        )
    await db_session.commit()
    return job_id


async def _write(db_session, tenant_key, **kwargs):
    return await write_360_memory(
        tenant_key=tenant_key,
        user_id=str(uuid.uuid4()),
        db_manager=MagicMock(),
        session=db_session,
        **kwargs,
    )


async def _closed_chain(db_session, tenant_key, product, *, head_worker_status="complete"):
    members = []
    for index in (1, 2):
        project = Project(
            id=str(uuid.uuid4()),
            name=f"Chain member P{index}",
            description="chain member",
            mission="member mission",
            status="active",
            tenant_key=tenant_key,
            product_id=product.id,
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        await db_session.commit()
        worker_status = head_worker_status if index == 1 else "complete"
        await _seed_job(db_session, tenant_key, project.id, "implementer", worker_status, [("Implement", "completed")])
        sub_orch = await _seed_job(
            db_session, tenant_key, project.id, "orchestrator", "complete", [("Coordinate", "completed")]
        )
        if worker_status == "complete":
            closeout = await _write(
                db_session,
                tenant_key,
                project_id=str(project.id),
                summary=f"P{index} done",
                key_outcomes=[f"P{index} shipped"],
                decisions_made=["member decision"],
                author_job_id=sub_orch,
            )
            assert closeout.get("entry_id"), closeout
            project.status = "completed"
            await db_session.commit()
        members.append(project)

    identity = await mint_conductor_job(db_session, tenant_key=tenant_key, run_id=f"run-{uuid.uuid4().hex[:8]}")
    conductor_job_id = identity["job_id"]
    execution = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.job_id == conductor_job_id, AgentExecution.tenant_key == tenant_key
            )
        )
    ).scalar_one()
    execution.status = "working"
    execution.started_at = datetime.now(UTC)
    for sequence, content in enumerate(DRIVE_TODOS):
        db_session.add(
            AgentTodoItem(
                job_id=conductor_job_id, tenant_key=tenant_key, content=content, status="completed", sequence=sequence
            )
        )
    await db_session.commit()
    return members, conductor_job_id


async def _conductor_finale(db_session, tenant_key, head_project_id, conductor_job_id):
    return await _write(
        db_session,
        tenant_key,
        project_id=str(head_project_id),
        author_job_id=conductor_job_id,
        summary="Chain run completed: 2 of 2 projects done.",
        key_outcomes=["P1 shipped", "P2 shipped"],
        decisions_made=["Sequential chain conductor auto-continued"],
        tags=["chore"],
    )


def test_protocol_prescribes_this_call_shape():
    source = Path(chapters_chain.__file__).read_text(encoding="utf-8")
    assert 'write_memory_entry(project_id=<resolved_order[0]>, author_job_id="{job_id_str}"' in source
    assert 'tags=["chore"]' in source
    assert "entry_type" not in source.split("SERIES SUMMARY", 1)[1].split("complete_job", 1)[0]


@pytest.mark.asyncio
async def test_conductor_series_summary_is_accepted(db_session, test_tenant_key, test_product):
    (head, _tail), conductor_job_id = await _closed_chain(db_session, test_tenant_key, test_product)

    result = await _conductor_finale(db_session, test_tenant_key, head.id, conductor_job_id)

    assert result.get("success") is not False, result
    assert result.get("entry_id"), result
    entry = (
        await db_session.execute(
            select(ProductMemoryEntry).where(
                ProductMemoryEntry.id == result["entry_id"], ProductMemoryEntry.tenant_key == test_tenant_key
            )
        )
    ).scalar_one()
    assert entry.entry_type == "project_completion"
    assert str(entry.project_id) == str(head.id)
    assert str(entry.author_job_id) == conductor_job_id


@pytest.mark.asyncio
async def test_open_genuine_work_todo_on_the_conductor_refuses_the_finale(db_session, test_tenant_key, test_product):
    (head, _tail), conductor_job_id = await _closed_chain(db_session, test_tenant_key, test_product)
    db_session.add(
        AgentTodoItem(
            job_id=conductor_job_id,
            tenant_key=test_tenant_key,
            content="Fix the failing test",
            status="in_progress",
            sequence=len(DRIVE_TODOS),
        )
    )
    await db_session.commit()

    result = await _conductor_finale(db_session, test_tenant_key, head.id, conductor_job_id)

    assert result.get("error") == "CLOSEOUT_BLOCKED", result
    assert result["summary"]["orchestrator_incomplete_todos"] == 1, result


@pytest.mark.asyncio
async def test_head_member_agent_still_working_refuses_the_finale(db_session, test_tenant_key, test_product):
    (head, _tail), conductor_job_id = await _closed_chain(
        db_session, test_tenant_key, test_product, head_worker_status="working"
    )

    result = await _conductor_finale(db_session, test_tenant_key, head.id, conductor_job_id)

    assert result.get("error") == "CLOSEOUT_BLOCKED", result
    assert result["summary"]["still_working"] == 1, result
