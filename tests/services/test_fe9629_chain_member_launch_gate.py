# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ImplementationNotReadyError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_completion_staging import is_staging_phase_orchestrator
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.services.sequence_chain_context import chain_member_phase
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _staging_service(db_manager, tenant_key, db_session) -> ProjectStagingService:
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session)


async def _seed_chain(db_session, tenant_key: str, *, current_index: int = 0, member_count: int = 2) -> dict:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"fe9629-product-{uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()

    projects: list[Project] = []
    for label in ("Alpha", "Beta", "Gamma")[:member_count]:
        project = Project(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"fe9629-{label}-{uuid4().hex[:8]}",
            description=f"FE-9629 chain member {label}.",
            mission=f"Build {label}.",
            status=ProjectStatus.INACTIVE,
            staging_status="staged",
            execution_mode="claude_code_cli",
            series_number=next_series_number(),
            created_at=datetime.now(UTC),
        )
        db_session.add(project)
        projects.append(project)
    await db_session.flush()

    run = SequenceRun(
        id=str(uuid4()),
        tenant_key=tenant_key,
        project_ids=[p.id for p in projects],
        resolved_order=[p.id for p in projects],
        current_index=current_index,
        execution_mode="claude_code_cli",
        status="running",
        chain_mission="Deliver the members in order.",
        project_statuses={p.id: "pending" for p in projects},
    )
    db_session.add(run)
    await db_session.flush()

    return {"run": run, "projects": projects}


async def _solo_project(db_session, tenant_key: str, *, staging_status: str = "staged") -> Project:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"fe9629-solo-product-{uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"fe9629-solo-{uuid4().hex[:8]}",
        description="FE-9629 solo control.",
        mission="Solo mission.",
        status=ProjectStatus.INACTIVE,
        staging_status=staging_status,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project




async def test_head_member_launches_from_staged(db_manager, db_session, test_tenant_key):
    seeded = await _seed_chain(db_session, test_tenant_key)
    head = seeded["projects"][0]
    svc = _staging_service(db_manager, test_tenant_key, db_session)

    result = await svc.launch_implementation(head.id, tenant_key=test_tenant_key)

    assert result["success"] is True
    assert result["implementation_launched_at"], "the member's launch gate must be stamped"
    await db_session.refresh(head)
    assert head.implementation_launched_at is not None
    assert head.staging_status == "staged", "launching a member must NOT fake its staging status"




async def test_member_beyond_index_is_refused_naming_its_predecessor(db_manager, db_session, test_tenant_key):
    seeded = await _seed_chain(db_session, test_tenant_key)
    head, second = seeded["projects"]
    svc = _staging_service(db_manager, test_tenant_key, db_session)

    with pytest.raises(ImplementationNotReadyError) as exc_info:
        await svc.launch_implementation(second.id, tenant_key=test_tenant_key)

    error = exc_info.value
    assert error.reason == "chain_predecessor_open", (
        f"a blocked member must be distinguishable from an unstaged solo project, got {error.reason!r}"
    )
    rendered = f"{error.message} {error.context}"
    assert head.alias in rendered, "the refusal must name the project the user is actually waiting on"
    assert error.context.get("predecessor_project_id") == head.id

    await db_session.refresh(second)
    assert second.implementation_launched_at is None, "a refused launch must never stamp the gate"




async def test_member_launches_after_predecessor_closes_out(db_manager, db_session, test_tenant_key):
    seeded = await _seed_chain(db_session, test_tenant_key)
    head, second = seeded["projects"]
    head.closeout_executed_at = datetime.now(UTC)
    await db_session.flush()

    svc = _staging_service(db_manager, test_tenant_key, db_session)
    result = await svc.launch_implementation(second.id, tenant_key=test_tenant_key)

    assert result["success"] is True
    run = await SequenceRunService(db_manager=db_manager, tenant_manager=TenantManager(), session=db_session).get(
        run_id=seeded["run"].id, tenant_key=test_tenant_key
    )
    assert run["current_index"] == 1, "crossing the launch gate must advance the chain to this member"
    assert run["project_statuses"][second.id] == "planning"




async def test_harness_door_refuses_the_same_member_with_an_actionable_error(db_manager, db_session, test_tenant_key):
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    seeded = await _seed_chain(db_session, test_tenant_key)
    head, second = seeded["projects"]

    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = test_tenant_key
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session)

    blocked = await accessor.launch_implementation(second.id, tenant_key=test_tenant_key)

    assert blocked["status"] == "gate_not_passed"
    assert blocked["reason"] == "chain_predecessor_open"
    assert head.alias in blocked["error"]
    assert "close" in str(blocked["next_action"]).lower()

    head.closeout_executed_at = datetime.now(UTC)
    await db_session.flush()
    launched = await accessor.launch_implementation(second.id, tenant_key=test_tenant_key)
    assert launched["status"] == "launched"




async def test_solo_project_still_requires_staging_complete(db_manager, db_session, test_tenant_key):
    project = await _solo_project(db_session, test_tenant_key, staging_status="staged")
    svc = _staging_service(db_manager, test_tenant_key, db_session)

    with pytest.raises(ImplementationNotReadyError) as exc_info:
        await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert exc_info.value.reason == "staging_incomplete"




@pytest.mark.parametrize(
    ("staging_status", "launched", "expected"),
    [
        ("staging", False, True),
        ("staged", False, True),
        ("staging_complete", False, True),
        ("staging_complete", True, False),
        ("staging", True, True),
        ("staged", True, True),
    ],
)
def test_staging_phase_orchestrator_truth_table(staging_status, launched, expected):
    job = SimpleNamespace(job_type="orchestrator")
    project = SimpleNamespace(
        staging_status=staging_status,
        implementation_launched_at=datetime.now(UTC) if launched else None,
    )
    assert is_staging_phase_orchestrator(job, project) is expected


def test_staging_phase_orchestrator_is_orchestrator_only():
    project = SimpleNamespace(staging_status="staging", implementation_launched_at=None)
    assert is_staging_phase_orchestrator(SimpleNamespace(job_type="implementer"), project) is False
    assert is_staging_phase_orchestrator(SimpleNamespace(job_type="orchestrator"), None) is False




@pytest.mark.parametrize(
    ("staging_status", "launched", "expected"),
    [
        ("staged", False, "staging"),
        ("staged", True, "staging"),
        ("staging", True, "staging"),
        ("staging_complete", False, "staging"),
        ("staging_complete", True, "implementation"),
    ],
)
def test_chain_member_phase_truth_table(staging_status, launched, expected):
    project = SimpleNamespace(
        staging_status=staging_status,
        implementation_launched_at=datetime.now(UTC) if launched else None,
    )
    assert chain_member_phase(project) == expected
