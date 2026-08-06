# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for MissionOrchestrationService (Sprint 002f -- P2 core).

Covers:
- get_staging_instructions happy path and error paths
- _check_staging_redirect static method
- _build_execution_mode_fields for CLI and multi-terminal modes
- Validation of empty job_id / tenant_key
- Tenant isolation on every query
"""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from giljo_mcp.exceptions import (
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TENANT_KEY = "test-tenant"
JOB_ID = "job-001"


def _make_session():
    """Create a mock async session configured as a context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    return session


def _make_service(session, tenant_key=TENANT_KEY):
    """Create a MissionOrchestrationService with injected test session."""
    db_manager = Mock()
    db_manager.get_session_async = Mock(return_value=session)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return MissionOrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=session,
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestGetOrchestratorInstructionsValidation:
    """Tests for input validation in get_staging_instructions."""

    @pytest.mark.asyncio
    async def test_empty_job_id_raises_validation_error(self):
        """Raises ValidationError when job_id is empty."""
        session = _make_session()
        service = _make_service(session)
        with pytest.raises(ValidationError, match="Job ID is required"):
            await service.get_staging_instructions("", TENANT_KEY)

    @pytest.mark.asyncio
    async def test_whitespace_job_id_raises_validation_error(self):
        """Raises ValidationError when job_id is whitespace."""
        session = _make_session()
        service = _make_service(session)
        with pytest.raises(ValidationError, match="Job ID is required"):
            await service.get_staging_instructions("   ", TENANT_KEY)

    @pytest.mark.asyncio
    async def test_empty_tenant_key_raises_validation_error(self):
        """Raises ValidationError when tenant_key is empty."""
        session = _make_session()
        service = _make_service(session)
        with pytest.raises(ValidationError, match="Tenant key is required"):
            await service.get_staging_instructions(JOB_ID, "")

    @pytest.mark.asyncio
    async def test_execution_not_found_raises(self):
        """Raises ResourceNotFoundError when execution does not exist."""
        session = _make_session()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        service = _make_service(session)
        with pytest.raises(ResourceNotFoundError, match="No execution found for job") as exc_info:
            await service.get_staging_instructions(JOB_ID, TENANT_KEY)
        assert exc_info.value.context["reason"] == "unknown_job_id"
        assert exc_info.value.context["next_action"]["tool"] == "diagnose_project_state"


# ---------------------------------------------------------------------------
# _check_staging_redirect tests
# ---------------------------------------------------------------------------


class TestCheckStagingRedirect:
    """Tests for the static staging redirect check."""

    def test_staging_not_complete_returns_none(self):
        """Returns None when staging_status is not staging_complete."""
        project = MagicMock()
        project.staging_status = "staging"
        result = MissionOrchestrationService._check_staging_redirect(project, JOB_ID)
        assert result is None

    def test_staging_complete_not_launched_returns_dashboard_message(self):
        """Returns redirect to dashboard when staging complete but not launched."""
        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = None
        project.id = "proj-1"
        project.name = "Test"
        result = MissionOrchestrationService._check_staging_redirect(project, JOB_ID)
        assert result is not None
        assert result["staging_complete"] is True
        assert result["redirect"] is None
        assert "dashboard" in result["message"].lower()

    def test_staging_complete_and_launched_redirects_to_mission(self):
        """Returns redirect to get_job_mission when implementation launched."""
        project = MagicMock()
        project.staging_status = "staging_complete"
        project.implementation_launched_at = "2026-01-01T00:00:00Z"
        project.id = "proj-1"
        project.name = "Test"
        result = MissionOrchestrationService._check_staging_redirect(project, JOB_ID)
        assert result is not None
        assert result["staging_complete"] is True
        assert result["redirect"] == "get_job_mission"
        assert "get_job_mission" in result["message"]


# ---------------------------------------------------------------------------
# _build_execution_mode_fields tests
# ---------------------------------------------------------------------------


class TestBuildExecutionModeFields:
    """Tests for execution-mode-specific field building."""

    def test_cli_mode_includes_cli_rules(self):
        """Claude Code CLI mode includes cli_mode_rules in response."""
        service = _make_service(_make_session())
        templates = [MagicMock(name="implementer"), MagicMock(name="tester")]
        fields = service._build_execution_mode_fields("claude_code_cli", templates, JOB_ID)
        assert "cli_mode_rules" in fields
        assert "phase_assignment_instructions" not in fields

    def test_codex_cli_mode_includes_codex_rules(self):
        """Codex CLI mode includes cli_mode_rules with codex-specific mapping.

        BE-9035c: the spawn syntax now derives from the RESOLVED HARNESS, not the
        (collapsed) execution_mode. To get the codex-specific mapping the caller
        passes resolved_harness='codex'; the subagent-folded execution_mode is
        immaterial to the spawn syntax now.
        """
        service = _make_service(_make_session())
        templates = [MagicMock(name="implementer")]
        fields = service._build_execution_mode_fields("codex_cli", templates, JOB_ID, resolved_harness="codex")
        assert "cli_mode_rules" in fields
        mapping = fields["cli_mode_rules"]["task_tool_mapping"]
        assert "gil-" in mapping
        assert "spawn_agent(agent='gil-" in mapping

    def test_gemini_cli_mode_includes_gemini_rules(self):
        """Gemini mode includes cli_mode_rules with gemini-specific mapping.

        BE-9035c: spawn syntax derives from the RESOLVED HARNESS, so pass
        resolved_harness='gemini' to exercise the gemini-specific @-syntax (not the
        harness-less generic mapping, which also happens to name @-mention)."""
        service = _make_service(_make_session())
        templates = [MagicMock(name="implementer")]
        fields = service._build_execution_mode_fields("gemini_cli", templates, JOB_ID, resolved_harness="gemini")
        assert "cli_mode_rules" in fields
        mapping = fields["cli_mode_rules"]["task_tool_mapping"]
        assert mapping.startswith("@{agent_name}"), "gemini renders its native @-syntax spawn mapping"

    def test_multi_terminal_mode_includes_phase_instructions(self):
        """Multi-terminal mode includes phase_assignment_instructions."""
        service = _make_service(_make_session())
        templates = [MagicMock(name="implementer")]
        fields = service._build_execution_mode_fields("multi_terminal", templates, JOB_ID)
        assert "phase_assignment_instructions" in fields
        assert "cli_mode_rules" not in fields
