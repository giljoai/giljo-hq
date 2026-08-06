# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for JobLifecycleService (Sprint 002f -- P1 security-critical).

Covers:
- spawn_job happy path and error paths
- Predecessor context injection
- Display name collision resolution
- Template resolution
- Orchestrator duplicate prevention
- Tenant isolation on every query
"""

import logging
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    ProjectStateError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services._predecessor_context import build_predecessor_context
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService


_TEST_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TENANT_KEY = "test-tenant"
PROJECT_ID = "proj-001"


def _make_session():
    """Create a mock async session configured as a context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = Mock()
    session.flush = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    return session


def _make_project(project_id=PROJECT_ID, status="active", execution_mode="multi_terminal"):
    """Create a mock Project model.

    ``status`` is coerced to a :class:`ProjectStatus` enum member to mirror
    real DB behavior (SQLAlchemy returns enum members from the typed
    ``project_status`` column). Tests may pass either a raw lifecycle string
    ("active", "completed", ...) or a :class:`ProjectStatus` member.
    """
    project = MagicMock()
    project.id = project_id
    project.name = "Test Project"
    project.status = ProjectStatus(status) if isinstance(status, str) else status
    project.tenant_key = TENANT_KEY
    project.execution_mode = execution_mode
    project.staging_status = None
    project.updated_at = None
    return project


def _make_service(session, tenant_key=TENANT_KEY):
    """Create a JobLifecycleService with injected test session."""
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return JobLifecycleService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=session,
    )


# ---------------------------------------------------------------------------
# spawn_job tests
# ---------------------------------------------------------------------------


class TestSpawnJob:
    """Tests for JobLifecycleService.spawn_job."""

    @pytest.mark.asyncio
    async def test_spawn_project_not_found_raises(self):
        """Raises ResourceNotFoundError when project does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="Project not found"):
            await service.spawn_job(
                agent_display_name="impl-1",
                agent_name="implementer",
                mission="Do something",
                project_id="nonexistent",
                tenant_key=TENANT_KEY,
            )

    @pytest.mark.asyncio
    async def test_spawn_into_completed_project_raises(self):
        """Raises ProjectStateError when project is completed."""
        project = _make_project(status="completed")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ProjectStateError, match="Cannot modify project"):
            await service.spawn_job(
                agent_display_name="impl-1",
                agent_name="implementer",
                mission="Do something",
                project_id=PROJECT_ID,
                tenant_key=TENANT_KEY,
            )

    @pytest.mark.asyncio
    async def test_spawn_into_cancelled_project_raises(self):
        """Raises ProjectStateError when project is cancelled."""
        project = _make_project(status="cancelled")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ProjectStateError, match="Cannot modify project"):
            await service.spawn_job(
                agent_display_name="impl-1",
                agent_name="implementer",
                mission="Do something",
                project_id=PROJECT_ID,
                tenant_key=TENANT_KEY,
            )

    @pytest.mark.asyncio
    async def test_spawn_sets_agent_execution_started_at(self, monkeypatch):
        """IMP-5036 task a8d7dac0: AgentExecution.started_at MUST be non-NULL
        after spawn. Repository queries that downstream-read order_by(started_at)
        and func.max(started_at) silently break on NULL rows; the spawn path
        is the single chokepoint that guarantees the invariant.
        """
        from datetime import UTC, datetime

        from giljo_mcp.services import job_lifecycle_service as jls_module

        project = _make_project(status="active")
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=mock_result)

        captured: dict = {}

        class _FakeRepo:
            async def persist_job_and_execution(self, **kwargs):
                captured["execution"] = kwargs["agent_execution"]
                captured["job"] = kwargs["agent_job"]
                return kwargs["agent_job"], kwargs["agent_execution"]

        monkeypatch.setattr(jls_module, "AgentCompletionRepository", _FakeRepo)

        service = _make_service(session)
        before = datetime.now(UTC)
        await service._create_job_and_execution_records(
            session=session,
            job_id="job-001",
            agent_id="agent-001",
            project=project,
            project_id=PROJECT_ID,
            tenant_key=TENANT_KEY,
            mission="Test mission",
            agent_display_name="impl-1",
            agent_name="implementer",
            parent_job_id=None,
            phase=None,
            resolved_template_id=None,
            metadata_dict={},
        )
        after = datetime.now(UTC)

        execution = captured["execution"]
        assert execution.started_at is not None, (
            "AgentExecution.started_at must be set at spawn (closes BE-staging-lock NULL gap)"
        )
        # Bound the timestamp to the spawn window so a future regression that
        # snapshots a stale timestamp also fails.
        assert before <= execution.started_at <= after, (
            f"started_at {execution.started_at} outside spawn window [{before}, {after}]"
        )


# ---------------------------------------------------------------------------
# _build_predecessor_context tests
# ---------------------------------------------------------------------------


class TestBuildPredecessorContext:
    """Tests for predecessor context injection."""

    @pytest.mark.asyncio
    async def test_predecessor_not_found_raises(self):
        """Raises ResourceNotFoundError when predecessor job does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ResourceNotFoundError, match="Predecessor job"):
            await build_predecessor_context(
                session=session,
                predecessor_job_id="nonexistent",
                tenant_key=TENANT_KEY,
                project_id=PROJECT_ID,
                mission="Fix bugs",
                agent_display_name="fixer",
                logger=_TEST_LOGGER,
            )

    @pytest.mark.asyncio
    async def test_predecessor_wrong_project_raises(self):
        """Raises ValidationError when predecessor belongs to different project."""
        pred_job = MagicMock()
        pred_job.project_id = "other-project"
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pred_job
        session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValidationError, match="different project"):
            await build_predecessor_context(
                session=session,
                predecessor_job_id="pred-job-1",
                tenant_key=TENANT_KEY,
                project_id=PROJECT_ID,
                mission="Fix bugs",
                agent_display_name="fixer",
                logger=_TEST_LOGGER,
            )

    @pytest.mark.asyncio
    async def test_predecessor_context_prepended_to_mission(self):
        """Predecessor context is prepended to mission string."""
        pred_job = MagicMock()
        pred_job.project_id = PROJECT_ID

        pred_execution = MagicMock()
        pred_execution.agent_display_name = "original-agent"
        pred_execution.result = {"summary": "Did some work", "commits": ["abc123"]}

        session = _make_session()

        call_count = 0
        mock_job_result = MagicMock()
        mock_job_result.scalar_one_or_none.return_value = pred_job
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = pred_execution

        async def side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_job_result
            return mock_exec_result

        session.execute = AsyncMock(side_effect=side_effect)

        result = await build_predecessor_context(
            session=session,
            predecessor_job_id="pred-job-1",
            tenant_key=TENANT_KEY,
            project_id=PROJECT_ID,
            mission="Fix the bugs",
            agent_display_name="fixer",
            logger=_TEST_LOGGER,
        )

        assert "PRIOR PHASE OUTPUT" in result
        assert "Fix the bugs" in result
        assert "original-agent" in result


# ---------------------------------------------------------------------------
# _resolve_display_name tests
# ---------------------------------------------------------------------------


class TestResolveDisplayName:
    """Tests for display name collision resolution."""

    @pytest.mark.asyncio
    async def test_unique_name_returned_as_is(self):
        """When name has no collision, it is returned unchanged."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service._resolve_display_name(session, "impl-frontend", TENANT_KEY, PROJECT_ID)
        assert result == "impl-frontend"

    @pytest.mark.asyncio
    async def test_collision_auto_suffixes(self):
        """When name collides, a numeric suffix is appended."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("impl-1",)]
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service._resolve_display_name(session, "impl-1", TENANT_KEY, PROJECT_ID)
        assert result == "impl-1-2"

    @pytest.mark.asyncio
    async def test_collision_finds_next_available_suffix(self):
        """When both name and name-2 are taken, returns name-3."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("impl-1",), ("impl-1-2",)]
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service._resolve_display_name(session, "impl-1", TENANT_KEY, PROJECT_ID)
        assert result == "impl-1-3"


# ---------------------------------------------------------------------------
# _validate_spawn_agent tests
# ---------------------------------------------------------------------------


class TestValidateSpawnAgent:
    """Tests for agent name validation and display name collision."""

    @pytest.mark.asyncio
    async def test_invalid_agent_name_raises(self):
        """Raises ValidationError when agent_name not in active templates."""
        session = _make_session()

        # Template lookup returns no matching names
        mock_template_result = MagicMock()
        mock_template_result.fetchall.return_value = [("implementer",), ("tester",)]
        session.execute = AsyncMock(return_value=mock_template_result)

        service = _make_service(session)
        with pytest.raises(ValidationError, match="Invalid agent_name"):
            await service._validate_spawn_agent(
                session=session,
                agent_display_name="my-agent",
                agent_name="nonexistent-template",
                tenant_key=TENANT_KEY,
                project_id=PROJECT_ID,
                parent_job_id=None,
            )

    @pytest.mark.asyncio
    async def test_duplicate_orchestrator_raises(self):
        """Raises AlreadyExistsError when active orchestrator exists."""
        existing_orch = MagicMock()
        existing_orch.agent_id = "existing-agent-id"
        existing_orch.status = "working"

        session = _make_session()
        mock_result = MagicMock()
        # find_active_orchestrator_in_project extracts via .scalars().first()
        # (BE-9242 FIX 1: multiplicity-tolerant, deterministic).
        mock_result.scalars.return_value.first.return_value = existing_orch
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(AlreadyExistsError, match="Orchestrator already exists"):
            await service._validate_spawn_agent(
                session=session,
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                tenant_key=TENANT_KEY,
                project_id=PROJECT_ID,
                parent_job_id=None,
            )

    @pytest.mark.asyncio
    async def test_orchestrator_succession_allowed(self):
        """Orchestrator succession (parent_job_id matches) is allowed."""
        existing_orch = MagicMock()
        existing_orch.agent_id = "existing-agent-id"
        existing_orch.status = "working"

        session = _make_session()
        mock_result = MagicMock()
        # find_active_orchestrator_in_project extracts via .scalars().first()
        # (BE-9242 FIX 1: multiplicity-tolerant, deterministic).
        mock_result.scalars.return_value.first.return_value = existing_orch
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        result = await service._validate_spawn_agent(
            session=session,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            tenant_key=TENANT_KEY,
            project_id=PROJECT_ID,
            parent_job_id="existing-agent-id",
        )
        assert result == "orchestrator"


# ---------------------------------------------------------------------------
# _build_agent_prompt tests
# ---------------------------------------------------------------------------


class TestBuildAgentPrompt:
    """Tests for thin agent prompt construction."""

    def test_prompt_contains_job_id(self):
        """The prompt includes the job_id for get_job_mission."""
        service = _make_service(_make_session())
        prompt = service._build_agent_prompt(
            agent_name="implementer",
            agent_display_name="impl-1",
            project_name="My Project",
            job_id="job-123",
        )
        # BE-9012d (F1): bare tool name (this prose reaches Codex/Gemini/Desktop
        # too, where the Claude Code mcp__giljo_mcp__ prefix is wrong).
        assert "get_job_mission" in prompt
        assert "mcp__giljo_mcp__get_job_mission" not in prompt
        assert 'job_id="job-123"' in prompt

    def test_prompt_does_not_pass_tenant_key(self):
        """
        The prompt MUST NOT instruct agents to pass tenant_key — the server
        auto-injects it from the API key session. Documenting it as a
        parameter would contradict the never-pass-tenant_key contract.
        """
        service = _make_service(_make_session())
        prompt = service._build_agent_prompt(
            agent_name="implementer",
            agent_display_name="impl-1",
            project_name="My Project",
            job_id="job-abc",
        )
        # No interpolated tenant_key value, no "tenant_key=" parameter form.
        assert TENANT_KEY not in prompt
        assert 'tenant_key="' not in prompt

    def test_orchestrator_prompt_includes_staging_rules(self):
        """Orchestrator prompt includes STAGING RULES section."""
        service = _make_service(_make_session())
        prompt = service._build_agent_prompt(
            agent_name="orchestrator",
            agent_display_name="orchestrator",
            project_name="My Project",
            job_id="job-456",
        )
        assert "STAGING RULES" in prompt

    def test_non_orchestrator_prompt_no_staging_rules(self):
        """Non-orchestrator prompt does not include STAGING RULES."""
        service = _make_service(_make_session())
        prompt = service._build_agent_prompt(
            agent_name="implementer",
            agent_display_name="impl-1",
            project_name="My Project",
            job_id="job-789",
        )
        assert "STAGING RULES" not in prompt


# ---------------------------------------------------------------------------
# _resolve_spawn_template tests
# ---------------------------------------------------------------------------


class TestResolveSpawnTemplate:
    """Tests for template ID resolution at spawn time.

    These stub the result object, so they assert how ``_resolve_spawn_template``
    HANDLES a row -- not what the query selects. BE-9325 is the standing reminder
    that they cannot see a WHERE-clause defect at all; the real-row coverage lives
    in ``tests/services/test_be9325_trashed_template_lifecycle.py`` and
    ``tests/integration/test_be9325_spawn_boundary_trashed_template.py``.

    BE-9325 moved the repository from ``scalar_one_or_none()`` to
    ``.scalars().first()`` so a duplicate name cannot raise instead of resolving.
    The stubs below follow that shape -- stubbing the old one silently returned a
    MagicMock chain that is not None, which is how the not-found case passed while
    asserting nothing.
    """

    @pytest.mark.asyncio
    async def test_template_found_returns_id(self):
        """When template exists, returns its ID."""
        template = MagicMock()
        template.id = "tmpl-abc"

        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = template
        session.execute = AsyncMock(return_value=mock_result)

        project = _make_project()
        service = _make_service(session)
        mission, template_id = await service._resolve_spawn_template(
            session=session,
            project=project,
            agent_name="implementer",
            mission="Do work",
            tenant_key=TENANT_KEY,
            agent_display_name="impl-1",
        )

        assert template_id == "tmpl-abc"
        assert mission == "Do work"

    @pytest.mark.asyncio
    async def test_template_not_found_returns_none(self):
        """When no matching template, returns None template_id."""
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        project = _make_project()
        service = _make_service(session)
        mission, template_id = await service._resolve_spawn_template(
            session=session,
            project=project,
            agent_name="unknown",
            mission="Do work",
            tenant_key=TENANT_KEY,
            agent_display_name="impl-1",
        )

        assert template_id is None
        assert mission == "Do work"

    @pytest.mark.asyncio
    async def test_failed_resolution_is_logged(self, caplog):
        """IMP-9342 item 4: a FAILED resolution must leave a log line.

        Resolution logged on success only, with no ``else`` branch, so an agent
        that silently lost its identity left nothing behind. An operator asking
        "why did this agent behave generically" had no line to correlate against
        -- the degradation was invisible in the logs as well as to the user.

        Asserted at the service layer because that is where the gap is: the
        method returns ``(mission, None)`` on both the healthy and the degraded
        path, so no caller and no boundary test can tell them apart.
        """
        session = _make_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        project = _make_project()
        service = _make_service(session)

        with caplog.at_level(logging.WARNING):
            _mission, template_id = await service._resolve_spawn_template(
                session=session,
                project=project,
                agent_name="retired-specialist",
                mission="Do work",
                tenant_key=TENANT_KEY,
                agent_display_name="impl-1",
            )

        assert template_id is None
        records = [r for r in caplog.records if "TEMPLATE_RESOLVE" in r.getMessage()]
        assert records, f"no [TEMPLATE_RESOLVE] failure log emitted; saw: {[r.getMessage() for r in caplog.records]}"
        assert records[0].levelno >= logging.WARNING, "a failed resolution must not be logged at INFO"
        # The agent name is the whole point -- it is what an operator correlates on.
        assert "retired-specialist" in records[0].getMessage() or "retired-specialist" in str(
            getattr(records[0], "agent_name", "")
        )
