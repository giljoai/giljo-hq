# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import DatabaseError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.repositories import (
    agent_completion_repository,
    agent_job_repository,
    auth_repository,
    configuration_repository,
    message_repository,
    mission_repository,
    org_repository,
    product_memory_repository,
    product_repository,
    progress_repository,
    project_lifecycle_repository,
    project_repository,
    settings_repository,
    task_repository,
    template_repository,
    user_repository,
    vision_document_repository,
)
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.repositories.agent_job_repository import AgentJobRepository
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.tenant import TenantManager




_COMMIT_RE = re.compile(r"\b(?:session|db)\.commit\s*\(")


_SWEPT_REPO_MODULES = [
    agent_job_repository,
    agent_completion_repository,
    configuration_repository,
    settings_repository,
    org_repository,
    product_repository,
    product_memory_repository,
    vision_document_repository,
    message_repository,
    template_repository,
    auth_repository,
    progress_repository,
    mission_repository,
    project_repository,
    project_lifecycle_repository,
    user_repository,
    task_repository,
]


@pytest.mark.parametrize(
    "module",
    _SWEPT_REPO_MODULES,
    ids=[m.__name__.rsplit(".", 1)[-1] for m in _SWEPT_REPO_MODULES],
)
def test_swept_repos_have_no_session_commit(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    offenders = [
        line.strip() for line in source.splitlines() if not line.lstrip().startswith("#") and _COMMIT_RE.search(line)
    ]
    assert offenders == [], (
        f"{Path(module.__file__).name} must not commit (repositories flush; the "
        f"session owner commits). Offending line(s): {offenders}"
    )


@pytest.mark.asyncio
async def test_persist_flushes_not_commits_failure_discards_row(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    job_id = str(uuid4())
    repo = AgentCompletionRepository()

    async def _persist_then_fail():
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            job = AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                job_type="implementer",
                mission="forced-failure mission",
                status="active",
                job_metadata={},
            )
            execution = AgentExecution(
                agent_id=str(uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="implementer",
                agent_name="impl",
                status="waiting",
                started_at=datetime.now(UTC),
            )
            await repo.persist_job_and_execution(session, job, execution)
            raise RuntimeError("boom before owner commit")

    with pytest.raises(RuntimeError, match="boom before owner commit"):
        await _persist_then_fail()

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        found = await AgentJobRepository(None).get_agent_job_by_job_id(session, tenant_key, job_id)
    assert found is None, "partial AgentJob persisted despite a failure before the owner commit"


@pytest.mark.asyncio
async def test_spawn_job_does_not_broadcast_when_commit_fails(db_session, db_manager, tenant_key, project):
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    service = JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )

    async def _boom():
        raise RuntimeError("commit boom")

    db_session.commit = _boom

    with pytest.raises(DatabaseError):
        await service.spawn_job(
            agent_display_name="impl",
            agent_name="specialist-1",
            mission="do work",
            project_id=project.id,
            tenant_key=tenant_key,
        )

    mock_ws.broadcast_to_tenant.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_job_broadcasts_after_successful_commit(db_session, db_manager, tenant_key, project):
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    service = JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )

    result = await service.spawn_job(
        agent_display_name="impl",
        agent_name="specialist-1",
        mission="do work",
        project_id=project.id,
        tenant_key=tenant_key,
    )

    assert result.job_id
    mock_ws.broadcast_to_tenant.assert_called_once()
    assert mock_ws.broadcast_to_tenant.call_args.kwargs.get("event_type") == "agent:created"
