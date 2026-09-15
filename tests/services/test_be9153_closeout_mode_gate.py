# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.user_approval import UserApproval
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.services.user_approval_service import UserApprovalService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


SIGNAL_RESULT = {"summary": "Work done, but two findings deferred", "deferred_findings": ["Race in reaper retry path"]}
CLEAN_RESULT = {"summary": "Straightforward change, all green", "files_changed": ["src/giljo_mcp/tools/foo.py"]}


async def _set_closeout_mode(db_session, tenant_key: str, mode: str) -> None:
    await SettingsService(db_session, tenant_key).update_settings("general", {"closeout_mode": mode})


async def _seed_closeout_orchestrator(db_session, tenant_key: str) -> dict:
    suffix = uuid4().hex[:8]
    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="be9153 museum",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return {"product": product, "project": project, "job": job, "execution": execution}


def _completion_service(db_manager, tenant_key, db_session) -> JobCompletionService:
    return JobCompletionService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )


async def _pending_gate_approval(db_session, tenant_key, execution_id):
    stmt = select(UserApproval).where(
        UserApproval.tenant_key == tenant_key,
        UserApproval.agent_execution_id == execution_id,
        UserApproval.status == "pending",
    )
    return (await db_session.execute(stmt)).scalar_one_or_none()


async def _reload_execution(db_session, tenant_key, execution_id) -> AgentExecution:
    stmt = select(AgentExecution).where(
        AgentExecution.tenant_key == tenant_key,
        AgentExecution.id == execution_id,
    )
    return (await db_session.execute(stmt)).scalar_one()




async def test_hitl_signal_closeout_blocks_with_pending_approval(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    await _set_closeout_mode(db_session, tenant_key, "hitl")
    seed = await _seed_closeout_orchestrator(db_session, tenant_key)
    svc = _completion_service(db_manager, tenant_key, db_session)

    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError):
        await svc.complete_job(
            job_id=seed["job"].job_id,
            result=SIGNAL_RESULT,
            tenant_key=tenant_key,
        )

    execution = await _reload_execution(db_session, tenant_key, seed["execution"].id)
    assert execution.status == "awaiting_user", "gate must park the orchestrator on a user_approval"
    approval = await _pending_gate_approval(db_session, tenant_key, seed["execution"].id)
    assert approval is not None, "gate must auto-create a pending approval for the deferred finding"




async def test_decide_resumes_and_recall_completes(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    await _set_closeout_mode(db_session, tenant_key, "hitl")
    seed = await _seed_closeout_orchestrator(db_session, tenant_key)
    svc = _completion_service(db_manager, tenant_key, db_session)

    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError):
        await svc.complete_job(job_id=seed["job"].job_id, result=SIGNAL_RESULT, tenant_key=tenant_key)

    approval = await _pending_gate_approval(db_session, tenant_key, seed["execution"].id)
    assert approval is not None

    approval_svc = UserApprovalService(db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session)
    option_id = (approval.options or [{"id": "approve"}])[0]["id"]
    await approval_svc.mark_decided(
        tenant_key=tenant_key,
        approval_id=approval.id,
        option_id=option_id,
        user_id=None,
        decided_via="mcp",
    )

    execution = await _reload_execution(db_session, tenant_key, seed["execution"].id)
    assert execution.status != "awaiting_user", "decide must clear the awaiting_user park (BE-9054)"

    result = await svc.complete_job(job_id=seed["job"].job_id, result=SIGNAL_RESULT, tenant_key=tenant_key)
    assert result.status == "success"
    execution = await _reload_execution(db_session, tenant_key, seed["execution"].id)
    assert execution.status == "complete"
    assert await _pending_gate_approval(db_session, tenant_key, seed["execution"].id) is None




async def test_hitl_clean_closeout_does_not_block(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    await _set_closeout_mode(db_session, tenant_key, "hitl")
    seed = await _seed_closeout_orchestrator(db_session, tenant_key)
    svc = _completion_service(db_manager, tenant_key, db_session)

    result = await svc.complete_job(job_id=seed["job"].job_id, result=CLEAN_RESULT, tenant_key=tenant_key)
    assert result.status == "success"
    execution = await _reload_execution(db_session, tenant_key, seed["execution"].id)
    assert execution.status == "complete"
    assert await _pending_gate_approval(db_session, tenant_key, seed["execution"].id) is None




async def test_autonomous_mode_never_blocks_even_with_signal(db_manager, db_session):
    tenant_key = TenantManager.generate_tenant_key()
    await _set_closeout_mode(db_session, tenant_key, "autonomous")
    seed = await _seed_closeout_orchestrator(db_session, tenant_key)
    svc = _completion_service(db_manager, tenant_key, db_session)

    result = await svc.complete_job(job_id=seed["job"].job_id, result=SIGNAL_RESULT, tenant_key=tenant_key)
    assert result.status == "success"
    execution = await _reload_execution(db_session, tenant_key, seed["execution"].id)
    assert execution.status == "complete"
    assert await _pending_gate_approval(db_session, tenant_key, seed["execution"].id) is None
