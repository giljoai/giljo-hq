# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-3006b: transaction-ownership convention regression tests (agent-jobs domain).

Convention (the TRANSACTION_OWNERSHIP_CONVENTION reference doc):
repositories FLUSH, the session OWNER (service entry point) COMMITS, and
WebSocket/EventBus events emit ONLY after the commit succeeds.

These tests pin the convention at the layer the bug occurred:

* ``test_swept_repos_have_no_session_commit`` -- grep-assert ratchet: zero
  ``session.commit()`` / ``db.commit()`` inside the two swept repositories.
* ``test_persist_flushes_not_commits_failure_discards_row`` -- forced-failure:
  a failure AFTER the (now flush-only) persist but BEFORE the owner commit
  leaves NO partial row. Pre-fix (repo committed mid-flow) the row survived.
* ``test_spawn_job_does_not_broadcast_when_commit_fails`` -- the event gate:
  if the owner commit fails, the ``agent:created`` event is NOT emitted (no
  phantom dashboard state).
* ``test_spawn_job_broadcasts_after_successful_commit`` -- happy-path load
  bearing: a successful spawn commits AND emits its event.

Parallel-safe: each DB-touching test owns its setup with a unique tenant key
(or the shared transactional ``db_session`` fixture); no module-level mutable
state; no test-ordering dependencies.
"""

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


# Re-export the tests/services/conftest.py fixtures used below so they resolve:
# ``tenant_key``, ``agent_templates``, ``project`` (successor-spawning fixtures).


_COMMIT_RE = re.compile(r"\b(?:session|db)\.commit\s*\(")


# Repositories swept to flush-only by the BE-3006 chain. The session owner
# (service entry point) commits; these modules must contain ZERO
# ``session.commit()`` / ``db.commit()``. BE-3006b seeded the agent-jobs pair;
# BE-3006c extends the ratchet to the remaining swept domains. Add each newly
# swept repository module here in the same commit that sweeps it.
_SWEPT_REPO_MODULES = [
    # BE-3006b (agent-jobs domain)
    agent_job_repository,
    agent_completion_repository,
    # BE-3006c -- org/settings/config domain
    configuration_repository,
    settings_repository,
    org_repository,
    # BE-3006c -- products domain
    product_repository,
    # BE-3006c -- memory/360 domain
    product_memory_repository,
    vision_document_repository,
    # BE-3006c -- messages domain
    message_repository,
    # BE-3006c -- templates domain
    template_repository,
    # BE-3006c -- auth domain
    auth_repository,
    # BE-3006c -- progress + mission domains
    progress_repository,
    mission_repository,
    # BE-3006c -- projects domain (project + project-lifecycle, incl. the
    # create_orchestrator_fixture flush + commit-before-broadcast fix)
    project_repository,
    project_lifecycle_repository,
    # BE-3006c -- user domain (Tier 2)
    user_repository,
    # BE-6086 -- task domain (final repo in the chain: task_repository was the
    # only remaining repo still committing; converting it closes out the
    # transaction-ownership convention across ALL repositories).
    task_repository,
]


@pytest.mark.parametrize(
    "module",
    _SWEPT_REPO_MODULES,
    ids=[m.__name__.rsplit(".", 1)[-1] for m in _SWEPT_REPO_MODULES],
)
def test_swept_repos_have_no_session_commit(module):
    """Ratchet: the swept repositories must never commit.

    Repositories flush; the session owner commits. Scans the module source,
    ignoring comment-only lines, for any ``session.commit(`` / ``db.commit(``.
    """
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
    """Forced-failure: a failure before the owner commit leaves no partial row.

    ``persist_job_and_execution`` now FLUSHES (not commits). When the caller
    raises before it commits, the session owner's rollback must discard the
    job+execution entirely. Pre-fix the repo committed mid-flow, so the row
    would survive this rollback -- this test would then fail.

    Uses real (committing) sessions, not the shared transactional fixture, so
    the commit-vs-flush distinction is observable. Unique tenant key keeps it
    parallel-safe; nothing is committed, so there is nothing to clean up.
    """
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
            # Failure AFTER the (flush-only) persist, BEFORE the owner commits.
            raise RuntimeError("boom before owner commit")

    with pytest.raises(RuntimeError, match="boom before owner commit"):
        await _persist_then_fail()

    # Fresh session: the job must NOT exist -- the flush was rolled back.
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        found = await AgentJobRepository(None).get_agent_job_by_job_id(session, tenant_key, job_id)
    assert found is None, "partial AgentJob persisted despite a failure before the owner commit"


@pytest.mark.asyncio
async def test_spawn_job_does_not_broadcast_when_commit_fails(db_session, db_manager, tenant_key, project):
    """Event gate: a failed owner commit must NOT emit the agent:created event.

    This is the phantom-dashboard-state guard -- the event may only fire after
    the write is durable.
    """
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    service = JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
        websocket_manager=mock_ws,
    )

    # Force the owner commit (spawn_job's explicit pre-broadcast commit) to fail.
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
    """Happy path (load-bearing): a successful spawn commits AND emits its event."""
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
