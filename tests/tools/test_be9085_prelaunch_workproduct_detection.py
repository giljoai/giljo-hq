# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentJob
from giljo_mcp.models.notifications import Notification
from giljo_mcp.tools.write_memory_entry import write_360_memory


@pytest.fixture(autouse=True)
def _stub_staleness():

    async def _noop(*args, **kwargs):
        return {"is_stale": False, "projects_since_tune": 0, "threshold": 3, "enabled": True}

    with patch(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        new=_noop,
    ):
        yield


def _mock_db_manager_over(db_session):
    mock_db_manager = MagicMock()

    @asynccontextmanager
    async def _yield_db_session():
        yield db_session

    mock_db_manager.get_session_async = MagicMock(side_effect=_yield_db_session)
    return mock_db_manager


async def _make_project(
    db_session,
    test_tenant_key,
    test_product,
    *,
    implementation_launched: bool,
    ever_launched: bool | None = None,
):
    if ever_launched is None:
        ever_launched = implementation_launched

    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9085 detector project",
        description="pre-launch workproduct detection",
        mission="test",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
        implementation_launched_at=datetime.now(UTC) if implementation_launched else None,
        ever_launched_at=datetime.now(UTC) if ever_launched else None,
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _orchestrator_job_id(db_session, tenant_key, project_id) -> str:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        mission="orchestrator",
        job_type="orchestrator",
        status="active",
        tenant_key=tenant_key,
    )
    db_session.add(job)
    await db_session.commit()
    return job.job_id


async def _open_notification(db_session, tenant_key, project_id):
    stmt = select(Notification).where(
        Notification.tenant_key == tenant_key,
        Notification.dedupe_key == f"project.pre_launch_workproduct:{project_id}",
        Notification.resolved_at.is_(None),
    )
    result = await db_session.execute(stmt)
    return result.scalars().first()


@pytest.mark.asyncio
async def test_never_launched_closeout_with_commits_fires_notification(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, never launched",
        key_outcomes=["shipped anyway"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
        git_commits=[{"sha": "a" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is not None
    assert notification.type == "project.pre_launch_workproduct"
    assert notification.severity == "warning"
    assert notification.payload["commit_count"] == 1
    assert notification.payload["project_id"] == str(project.id)
    assert "false alarm" not in notification.body.lower()


@pytest.mark.asyncio
async def test_notification_is_emitted_to_the_bell_surface(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, never launched",
        key_outcomes=["shipped anyway"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
        git_commits=[{"sha": "b" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is not None
    assert notification.surface == "bell"


@pytest.mark.asyncio
async def test_enriched_notification_carries_taxonomy_alias_and_name(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, never launched",
        key_outcomes=["shipped anyway"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
        git_commits=[{"sha": "e" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is not None
    alias = notification.payload["taxonomy_alias"]
    assert alias, "enriched notification should carry a non-empty taxonomy_alias"
    assert notification.payload["project_name"] == "BE-9085 detector project"
    assert notification.payload["commit_count"] == 1
    assert alias in notification.title
    assert alias in notification.body
    assert "BE-9085 detector project" in notification.body
    assert "headless" in notification.body.lower()
    assert "ever_launched_at" not in notification.body


@pytest.mark.asyncio
async def test_launched_project_with_commits_no_notification(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=True)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, properly launched",
        key_outcomes=["shipped"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
        git_commits=[{"sha": "b" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is None


@pytest.mark.asyncio
async def test_prelaunch_closeout_with_no_commits_no_notification(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with no commits, never launched",
        key_outcomes=["nothing shipped"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
        git_commits=[],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is None


@pytest.mark.asyncio
async def test_fail_open_closeout_still_succeeds_when_emit_raises(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    with patch(
        "giljo_mcp.services.notification_service.NotificationService.upsert_by_dedupe_key",
        new=AsyncMock(side_effect=RuntimeError("simulated notification backend failure")),
    ):
        result = await write_360_memory(
            project_id=str(project.id),
            tenant_key=test_tenant_key,
            summary="Closeout where the notification emit blows up",
            key_outcomes=["shipped anyway"],
            decisions_made=["decision"],
            entry_type="project_completion",
            author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
            git_commits=[{"sha": "c" * 40, "message": "fix", "author": "agent"}],
            db_manager=db_manager,
            session=db_session,
        )

    assert result.get("entry_id"), "closeout must still succeed when the detector's emit raises"
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_restage_survivor_suppresses_alarm(db_session, test_tenant_key, test_product):
    project = await _make_project(
        db_session,
        test_tenant_key,
        test_product,
        implementation_launched=False,
        ever_launched=True,
    )
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout after a restage that cleared implementation_launched_at",
        key_outcomes=["restaged then closed without relaunching"],
        decisions_made=["decision"],
        entry_type="project_completion",
        author_job_id=await _orchestrator_job_id(db_session, test_tenant_key, project.id),
        git_commits=[{"sha": "d" * 40, "message": "pre-restage work", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is None, "ever_launched_at must suppress the restage false-positive"
