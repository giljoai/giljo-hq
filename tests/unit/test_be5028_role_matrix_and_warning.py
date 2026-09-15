# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.tools.write_memory_entry import (
    ORCHESTRATOR_ONLY_ENTRY_TYPES,
    WORKER_ALLOWED_ENTRY_TYPES,
    write_360_memory,
)




@pytest_asyncio.fixture
async def linked_project(db_session, test_tenant_key, test_product):
    project = Project(
        id=str(uuid.uuid4()),
        name="BE-5028 Verification Project",
        description="Project for matrix and warning-suppression verification",
        mission="Verify BE-5028 Phase 1 + Phase 2",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _make_agent_job(db_session, tenant_key: str, project_id: str, job_type: str) -> AgentJob:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        project_id=project_id,
        mission=f"Test {job_type} mission",
        job_type=job_type,
        status="active",
        tenant_key=tenant_key,
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_name=job_type,
        agent_display_name=job_type,
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return job


@pytest_asyncio.fixture
async def orchestrator_job(db_session, test_tenant_key, linked_project):
    return await _make_agent_job(db_session, test_tenant_key, linked_project.id, "orchestrator")


@pytest_asyncio.fixture
async def worker_job(db_session, test_tenant_key, linked_project):
    return await _make_agent_job(db_session, test_tenant_key, linked_project.id, "implementer")


def _mock_db_manager(db_session):
    mgr = MagicMock()
    mgr.get_session_async = MagicMock()
    mgr.get_session_async.return_value.__aenter__ = AsyncMock(return_value=db_session)
    mgr.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)
    return mgr




ALL_MATRIX_ENTRY_TYPES = sorted(WORKER_ALLOWED_ENTRY_TYPES | ORCHESTRATOR_ONLY_ENTRY_TYPES)
assert len(ALL_MATRIX_ENTRY_TYPES) >= 6, "Matrix sanity: at least 4 worker + 2 orchestrator"


class TestAuthorizationMatrix:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entry_type", ALL_MATRIX_ENTRY_TYPES)
    async def test_orchestrator_caller_passes_matrix_for_all_seven_types(
        self,
        entry_type,
        db_session,
        test_tenant_key,
        linked_project,
        orchestrator_job,
    ):
        mock_mgr = _mock_db_manager(db_session)
        with (
            patch(
                "giljo_mcp.tools.write_memory_entry._check_closeout_readiness",
                new=AsyncMock(return_value=(True, {})),
            ),
            patch(
                "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
                new_callable=AsyncMock,
            ),
            patch(
                "giljo_mcp.tools.write_memory_entry.emit_websocket_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await write_360_memory(
                project_id=str(linked_project.id),
                tenant_key=test_tenant_key,
                summary="Matrix verification headline.",
                key_outcomes=["k"],
                decisions_made=["d"],
                entry_type=entry_type,
                author_job_id=orchestrator_job.job_id,
                git_commits=[],
                tags=[],
                db_manager=mock_mgr,
                session=db_session,
            )
        assert isinstance(result, dict)
        assert result.get("error") != "ORCHESTRATOR_ONLY_ENTRY_TYPE", (
            f"Orchestrator should not be blocked from writing {entry_type!r}; got: {result}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entry_type", sorted(WORKER_ALLOWED_ENTRY_TYPES))
    async def test_worker_caller_passes_matrix_for_worker_allowed_types(
        self,
        entry_type,
        db_session,
        test_tenant_key,
        linked_project,
        worker_job,
    ):
        mock_mgr = _mock_db_manager(db_session)
        with (
            patch(
                "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
                new_callable=AsyncMock,
            ),
            patch(
                "giljo_mcp.tools.write_memory_entry.emit_websocket_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await write_360_memory(
                project_id=str(linked_project.id),
                tenant_key=test_tenant_key,
                summary="Worker-allowed entry headline.",
                key_outcomes=["k"],
                decisions_made=["d"],
                entry_type=entry_type,
                author_job_id=worker_job.job_id,
                git_commits=[],
                tags=[],
                db_manager=mock_mgr,
                session=db_session,
            )
        assert isinstance(result, dict)
        assert result.get("error") != "ORCHESTRATOR_ONLY_ENTRY_TYPE", (
            f"Worker must be allowed to write {entry_type!r}; got: {result}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entry_type", sorted(ORCHESTRATOR_ONLY_ENTRY_TYPES))
    async def test_worker_caller_rejected_for_orchestrator_only_types(
        self,
        entry_type,
        db_session,
        test_tenant_key,
        linked_project,
        worker_job,
    ):
        mock_mgr = _mock_db_manager(db_session)
        with patch(
            "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
            new_callable=AsyncMock,
        ):
            result = await write_360_memory(
                project_id=str(linked_project.id),
                tenant_key=test_tenant_key,
                summary="Worker attempting closeout-shaped write.",
                key_outcomes=["k"],
                decisions_made=["d"],
                entry_type=entry_type,
                author_job_id=worker_job.job_id,
                git_commits=[],
                tags=[],
                db_manager=mock_mgr,
                session=db_session,
            )
        assert result["success"] is False
        assert result["error"] == "ORCHESTRATOR_ONLY_ENTRY_TYPE"
        assert result["entry_type"] == entry_type
        assert result["calling_agent_role"] == "implementer"




@pytest.mark.asyncio
async def test_rejection_shape_has_all_required_keys(db_session, test_tenant_key, linked_project, worker_job):
    mock_mgr = _mock_db_manager(db_session)
    with patch(
        "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
        new_callable=AsyncMock,
    ):
        result = await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="shape test",
            key_outcomes=["k"],
            decisions_made=["d"],
            entry_type="project_completion",
            author_job_id=worker_job.job_id,
            git_commits=[],
            tags=[],
            db_manager=mock_mgr,
            session=db_session,
        )

    expected_keys = {
        "success",
        "error",
        "entry_type",
        "calling_agent_role",
        "message",
        "allowed_for_workers",
    }
    assert expected_keys.issubset(result.keys()), f"Missing keys in rejection: {expected_keys - set(result.keys())}"

    assert result["success"] is False
    assert result["error"] == "ORCHESTRATOR_ONLY_ENTRY_TYPE"
    assert result["entry_type"] == "project_completion"
    assert result["calling_agent_role"] == "implementer"
    assert isinstance(result["message"], str)
    assert len(result["message"]) > 0
    assert isinstance(result["allowed_for_workers"], list)
    assert result["allowed_for_workers"] == sorted(WORKER_ALLOWED_ENTRY_TYPES)


@pytest.mark.asyncio
async def test_rejection_does_not_raise_exception(db_session, test_tenant_key, linked_project, worker_job):
    mock_mgr = _mock_db_manager(db_session)
    with patch(
        "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
        new_callable=AsyncMock,
    ):
        result = await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="no exception",
            key_outcomes=["k"],
            decisions_made=["d"],
            entry_type="session_handover",
            author_job_id=worker_job.job_id,
            git_commits=[],
            tags=[],
            db_manager=mock_mgr,
            session=db_session,
        )
    assert result["error"] == "ORCHESTRATOR_ONLY_ENTRY_TYPE"




@pytest.mark.asyncio
async def test_caller_role_unknown_when_job_lookup_returns_none(db_session, test_tenant_key, linked_project):
    mock_mgr = _mock_db_manager(db_session)
    bogus_job_id = str(uuid.uuid4())
    with patch(
        "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
        new_callable=AsyncMock,
    ):
        result = await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="unknown caller",
            key_outcomes=["k"],
            decisions_made=["d"],
            entry_type="project_completion",
            author_job_id=bogus_job_id,
            git_commits=[],
            tags=[],
            db_manager=mock_mgr,
            session=db_session,
        )
    assert result["success"] is False
    assert result["error"] == "ORCHESTRATOR_ONLY_ENTRY_TYPE"
    assert result["calling_agent_role"] == "unknown"


@pytest.mark.asyncio
async def test_caller_role_lookup_uses_tenant_key(db_session, test_tenant_key, linked_project, orchestrator_job):
    mock_mgr = _mock_db_manager(db_session)
    with (
        patch("giljo_mcp.tools.write_memory_entry.AgentCompletionRepository") as mock_repo_cls,
        patch(
            "giljo_mcp.tools.write_memory_entry._check_closeout_readiness",
            new=AsyncMock(return_value=(True, {})),
        ),
        patch(
            "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
            new_callable=AsyncMock,
        ),
        patch(
            "giljo_mcp.tools.write_memory_entry.emit_websocket_event",
            new_callable=AsyncMock,
        ),
    ):
        mock_repo = MagicMock()
        mock_repo.get_agent_job_by_job_id = AsyncMock(return_value=orchestrator_job)
        mock_repo_cls.return_value = mock_repo

        await write_360_memory(
            project_id=str(linked_project.id),
            tenant_key=test_tenant_key,
            summary="tenant-key-lookup verification",
            key_outcomes=["k"],
            decisions_made=["d"],
            entry_type="project_completion",
            author_job_id=orchestrator_job.job_id,
            git_commits=[],
            tags=[],
            db_manager=mock_mgr,
            session=db_session,
        )

        mock_repo.get_agent_job_by_job_id.assert_awaited()
        call_args = mock_repo.get_agent_job_by_job_id.await_args
        assert call_args.args[1] == test_tenant_key
        assert call_args.args[2] == orchestrator_job.job_id




@pytest.mark.asyncio
async def test_cross_tenant_orchestrator_cannot_authorize_write_in_another_tenant(
    db_session, test_tenant_key, test_product
):
    tenant_a = test_tenant_key
    project_a = Project(
        id=str(uuid.uuid4()),
        name="Tenant A project",
        description="x",
        mission="x",
        status="active",
        tenant_key=tenant_a,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_a)
    await db_session.commit()

    orch_job_a = await _make_agent_job(db_session, tenant_a, project_a.id, "orchestrator")

    from giljo_mcp.models import Product

    tenant_b = "tk_isolated_other_tenant_" + uuid.uuid4().hex[:8]
    product_b = Product(
        id=str(uuid.uuid4()),
        name="Tenant B product",
        description="x",
        tenant_key=tenant_b,
        is_active=True,
        product_memory={},
    )
    db_session.add(product_b)
    project_b = Project(
        id=str(uuid.uuid4()),
        name="Tenant B project",
        description="x",
        mission="x",
        status="active",
        tenant_key=tenant_b,
        product_id=product_b.id,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project_b)
    await db_session.commit()

    mock_mgr = _mock_db_manager(db_session)
    with patch(
        "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
        new_callable=AsyncMock,
    ):
        result = await write_360_memory(
            project_id=str(project_b.id),
            tenant_key=tenant_b,
            summary="cross-tenant spoofing attempt",
            key_outcomes=["k"],
            decisions_made=["d"],
            entry_type="project_completion",
            author_job_id=orch_job_a.job_id,
            git_commits=[],
            tags=[],
            db_manager=mock_mgr,
            session=db_session,
        )

    assert result["success"] is False
    assert result["error"] == "ORCHESTRATOR_ONLY_ENTRY_TYPE"
    assert result["calling_agent_role"] == "unknown"




class TestCompleteJobWarningSuppression:

    @pytest.fixture
    def completion_service(self, db_session, test_tenant_key):
        db_manager = MagicMock()
        tenant_manager = MagicMock()
        tenant_manager.get_current_tenant.return_value = test_tenant_key
        return JobCompletionService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            test_session=db_session,
        )

    @pytest.mark.asyncio
    async def test_complete_job_does_not_emit_legacy_360_memory_warning(
        self, completion_service, db_session, test_tenant_key, linked_project
    ):
        orch = await _make_agent_job(db_session, test_tenant_key, linked_project.id, "orchestrator")

        result = await completion_service.complete_job(
            job_id=orch.job_id,
            result={"summary": "Verification of warning suppression."},
            tenant_key=test_tenant_key,
        )

        flat_warnings = " ".join(getattr(result, "warnings", []) or [])
        assert "360 memory has not been written" not in flat_warnings, (
            "Fix A regression: legacy 360 memory warning has reappeared."
        )
        assert "the closeout is incomplete" not in flat_warnings, (
            "Fix A regression: 'closeout is incomplete' wording has reappeared."
        )

        assert getattr(result, "closeout_checklist", None) is not None




class TestValidEntryTypeFrozenset:

    EXPECTED_ADMITTED: ClassVar[set[str]] = {
        "project_completion",
        "handover_closeout",
        "session_handover",
        "baseline",
        "decision",
        "architecture",
        "discovery",
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entry_type", sorted(EXPECTED_ADMITTED))
    async def test_admits_all_eight_canonical_entry_types(
        self,
        entry_type,
        db_session,
        test_tenant_key,
        linked_project,
        orchestrator_job,
    ):
        mock_mgr = _mock_db_manager(db_session)
        with (
            patch(
                "giljo_mcp.tools.write_memory_entry._check_closeout_readiness",
                new=AsyncMock(return_value=(True, {})),
            ),
            patch(
                "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
                new_callable=AsyncMock,
            ),
            patch(
                "giljo_mcp.tools.write_memory_entry.emit_websocket_event",
                new_callable=AsyncMock,
            ),
        ):
            try:
                result = await write_360_memory(
                    project_id=str(linked_project.id),
                    tenant_key=test_tenant_key,
                    summary=f"vocab test for {entry_type}",
                    key_outcomes=["k"],
                    decisions_made=["d"],
                    entry_type=entry_type,
                    author_job_id=orchestrator_job.job_id,
                    git_commits=[],
                    tags=[],
                    db_manager=mock_mgr,
                    session=db_session,
                )
            except ValidationError as e:
                pytest.fail(f"valid_entry_types regression: {entry_type!r} raised ValidationError: {e}")
            assert result.get("error") != "ORCHESTRATOR_ONLY_ENTRY_TYPE"

    @pytest.mark.asyncio
    async def test_typo_entry_type_still_raises_validation_error(
        self, db_session, test_tenant_key, linked_project, orchestrator_job
    ):
        mock_mgr = _mock_db_manager(db_session)
        with (
            patch(
                "giljo_mcp.tools.write_memory_entry._check_and_emit_tuning_staleness",
                new_callable=AsyncMock,
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            await write_360_memory(
                project_id=str(linked_project.id),
                tenant_key=test_tenant_key,
                summary="typo test",
                key_outcomes=["k"],
                decisions_made=["d"],
                entry_type="desicion",
                author_job_id=orchestrator_job.job_id,
                git_commits=[],
                tags=[],
                db_manager=mock_mgr,
                session=db_session,
            )
        assert "Invalid entry_type" in str(exc_info.value)
