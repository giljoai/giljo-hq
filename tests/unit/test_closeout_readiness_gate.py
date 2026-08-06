# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for closeout readiness gate in close_project_and_update_memory (Bug Fix Feb 2026).

Tests cover:
1. CLOSEOUT_BLOCKED returned when agents are still active
2. force=True auto-decommissions active agents and proceeds
3. All-complete agents pass the gate normally
4. Decommissioned agents are skipped (don't block)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tools.project_closeout import (
    _check_agent_readiness,
    _force_decommission_agents,
    close_project_and_update_memory,
)


def _make_execution(
    agent_id: str,
    display_name: str,
    status: str = "complete",
    job_id: str | None = None,
    tenant_key: str = "test-tenant",
    messages_waiting: int = 0,
) -> Mock:
    """Create a mock AgentExecution."""
    exe = Mock(spec=AgentExecution)
    exe.agent_id = agent_id
    exe.agent_display_name = display_name
    exe.agent_name = display_name
    exe.status = status
    exe.job_id = job_id or str(uuid4())
    exe.tenant_key = tenant_key
    exe.messages_waiting_count = messages_waiting
    exe.started_at = datetime.now(UTC)
    exe.id = exe.job_id
    return exe


def _execute_then_empty(executions):
    """Build a ``session.execute`` side_effect for the BE-3010c readiness gathering.

    The unified ``evaluate_closeout_readiness`` issues one execution-scan query
    followed by per-agent TODO queries (and, for awaiting_user agents, an approval
    lookup). TSK-9268 added one batched live action-required-unread query (the
    ack-based store the drain writes), which consumes ``result.all()`` — so every
    result also serves an empty iterable there. Returns the execution list for the
    first call and an empty result for every subsequent call.
    """
    state = {"n": 0}

    async def _execute(*_args, **_kwargs):
        state["n"] += 1
        result = Mock()
        scalars = Mock()
        scalars.all.return_value = executions if state["n"] == 1 else []
        result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        return result

    return _execute


class TestCheckAgentReadiness:
    """Tests for _check_agent_readiness helper."""

    @pytest.mark.asyncio
    async def test_all_complete_returns_ready(self):
        """When all agents are complete, readiness check passes."""
        session = AsyncMock()
        project_id = str(uuid4())

        agent_a = _make_execution(str(uuid4()), "impl-1", "complete")
        agent_b = _make_execution(str(uuid4()), "analyzer-1", "complete")

        # BE-3010c: the unified readiness gathering queries each non-skipped
        # agent's TODOs (the superset B needs), so the mock returns the execution
        # list for the first (scan) query and empty for subsequent TODO queries.
        session.execute = AsyncMock(side_effect=_execute_then_empty([agent_a, agent_b]))

        is_ready, blockers = await _check_agent_readiness(session, project_id, "test-tenant")

        assert is_ready is True
        assert blockers == []

    @pytest.mark.asyncio
    async def test_active_agents_return_blockers(self):
        """When agents are still working/blocked/silent, blockers are returned."""
        session = AsyncMock()
        project_id = str(uuid4())

        agent_a = _make_execution(str(uuid4()), "impl-1", "complete")
        agent_b = _make_execution(str(uuid4()), "ui-builder", "working")
        agent_c = _make_execution(str(uuid4()), "tester", "silent")

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = Mock()
            # TSK-9268: the live action-required-unread query consumes result.all().
            result.all.return_value = []
            if call_count["n"] == 1:
                # Execution query
                scalars = Mock()
                scalars.all.return_value = [agent_a, agent_b, agent_c]
                result.scalars.return_value = scalars
            else:
                # Todo queries — return empty
                scalars = Mock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        is_ready, blockers = await _check_agent_readiness(session, project_id, "test-tenant")

        assert is_ready is False
        agent_blockers = [b for b in blockers if "_summary" not in b]
        assert len(agent_blockers) == 2
        blocker_names = {b["agent_name"] for b in agent_blockers}
        assert "ui-builder" in blocker_names
        assert "tester" in blocker_names
        # Verify enriched fields
        for b in agent_blockers:
            assert "issue_type" in b
            assert "suggested_action" in b
            assert b["issue_type"] == "still_working"

    @pytest.mark.asyncio
    async def test_decommissioned_agents_skipped(self):
        """Decommissioned agents should not block closeout."""
        session = AsyncMock()
        project_id = str(uuid4())

        agent_a = _make_execution(str(uuid4()), "impl-1", "complete")
        agent_b = _make_execution(str(uuid4()), "retired-agent", "decommissioned")

        session.execute = AsyncMock(side_effect=_execute_then_empty([agent_a, agent_b]))

        is_ready, blockers = await _check_agent_readiness(session, project_id, "test-tenant")

        assert is_ready is True
        assert blockers == []

    @pytest.mark.asyncio
    async def test_empty_project_returns_ready(self):
        """A project with no agents should be closeable."""
        session = AsyncMock()
        project_id = str(uuid4())

        scalars_mock = Mock()
        scalars_mock.all.return_value = []
        result_mock = Mock()
        result_mock.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=result_mock)

        is_ready, blockers = await _check_agent_readiness(session, project_id, "test-tenant")

        assert is_ready is True
        assert blockers == []


class TestForceDecommissionAgents:
    """Tests for _force_decommission_agents helper."""

    @pytest.mark.asyncio
    async def test_active_agents_decommissioned(self):
        """Active agents should be set to decommissioned status."""
        session = AsyncMock()
        project_id = str(uuid4())

        agent_working = _make_execution(str(uuid4()), "ui-builder", "working")
        agent_silent = _make_execution(str(uuid4()), "tester", "silent")

        # BE-9242: decommissioning now also resolves each agent's dead message
        # cursors (resolve_terminal_agent_cursors), which issues one extra
        # lookup query per decommissioned agent. Returns the executions-to-
        # decommission list for the first (scan) call and empty for every
        # subsequent per-agent cursor lookup -- same pattern as
        # ``_execute_then_empty`` above.
        session.execute = AsyncMock(side_effect=_execute_then_empty([agent_working, agent_silent]))

        decommissioned = await _force_decommission_agents(session, project_id, "test-tenant")

        assert len(decommissioned) == 2
        assert agent_working.status == "decommissioned"
        assert agent_silent.status == "decommissioned"
        assert "ui-builder" in decommissioned
        assert "tester" in decommissioned
        # No live unread cursors were found for either agent (all subsequent
        # queries returned empty), so no additional ack-driven flush fires --
        # the final decommission_project_agents flush is still the only one.
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_active_agents_returns_empty(self):
        """When no active agents exist, nothing should be decommissioned."""
        session = AsyncMock()
        project_id = str(uuid4())

        scalars_mock = Mock()
        scalars_mock.all.return_value = []
        result_mock = Mock()
        result_mock.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=result_mock)

        decommissioned = await _force_decommission_agents(session, project_id, "test-tenant")

        assert decommissioned == []
        session.flush.assert_not_awaited()


class TestCloseoutGateIntegration:
    """Integration tests for the readiness gate in close_project_and_update_memory."""

    @pytest.mark.asyncio
    async def test_blocked_when_agents_active_and_no_force(self):
        """Without force=True, closeout should be blocked when agents are active."""
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.tenant_key = tenant_key
        mock_project.product_id = product_id

        mock_product = MagicMock(spec=Product)
        mock_product.id = product_id
        mock_product.tenant_key = tenant_key
        mock_product.product_memory = {}

        # Agent that is still working
        agent_working = _make_execution(str(uuid4()), "impl-1", "working")

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            # TSK-9268: the readiness gathering now issues a batched live
            # action-required-unread query (call 5) that consumes result.all().
            result.all.return_value = []
            if call_count["n"] == 1:
                # Project lookup
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                # Product lookup
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                # Agent readiness check
                scalars = MagicMock()
                scalars.all.return_value = [agent_working]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                # Todo query for the working agent — return empty
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        # BE-9016 (Sentry GILJOAI-BACKEND-5): CLOSEOUT_BLOCKED is an EXPECTED,
        # agent-actionable domain rejection (BE-6081 Tier 2) -- it must be
        # RETURNED as a structured dict, not raised, so it never reaches Sentry
        # as an error-level event. Was: pytest.raises(ProjectStateError).
        result = await close_project_and_update_memory(
            project_id=project_id,
            summary="Test summary for closeout",
            key_outcomes=["outcome-1"],
            decisions_made=["decision-1"],
            tenant_key=tenant_key,
            db_manager=mock_db_manager,
            force=False,
        )

        assert result["success"] is False
        assert result["error"] == "CLOSEOUT_BLOCKED"
        assert result["project_id"] == project_id
        assert "blockers" in result
        agent_blockers = [b for b in result["blockers"] if "_summary" not in b]
        assert len(agent_blockers) == 1
        assert agent_blockers[0]["agent_name"] == "impl-1"
        assert agent_blockers[0]["issue_type"] == "still_working"

    @pytest.mark.asyncio
    async def test_force_decommissions_and_proceeds(self):
        """With force=True, active agents should be decommissioned and closeout should proceed."""
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.tenant_key = tenant_key
        mock_project.product_id = product_id
        mock_project.created_at = datetime.now(UTC)
        mock_project.completed_at = None

        mock_project.name = "Test Project"

        mock_product = MagicMock(spec=Product)
        mock_product.id = product_id
        mock_product.tenant_key = tenant_key
        mock_product.product_memory = {}

        agent_working = _make_execution(str(uuid4()), "impl-1", "working")

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            # TSK-9268: live action-required-unread query added at call 5.
            result.all.return_value = []
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                # Readiness check — returns working agent
                scalars = MagicMock()
                scalars.all.return_value = [agent_working]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                # Todo query for the working agent — return empty
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                # Orchestrator guard query — no active orchestrator (agent is "impl-1")
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 7:
                # Force decommission query — returns same working agent
                scalars = MagicMock()
                scalars.all.return_value = [agent_working]
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        # Mock the ProductMemoryRepository to avoid real DB writes
        mock_entry = MagicMock()
        mock_entry.id = str(uuid4())
        mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

        # BE-5022b: project_closeout now routes through ProductMemoryService
        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_cls:
            repo_instance = mock_svc_cls.return_value
            repo_instance.get_next_sequence = AsyncMock(return_value=1)
            repo_instance.create_entry = AsyncMock(return_value=mock_entry)

            with patch(
                "giljo_mcp.tools.project_closeout.emit_websocket_event",
                new_callable=AsyncMock,
            ):
                result = await close_project_and_update_memory(
                    project_id=project_id,
                    summary="Test summary for closeout",
                    key_outcomes=["outcome-1"],
                    decisions_made=["decision-1"],
                    tenant_key=tenant_key,
                    db_manager=mock_db_manager,
                    force=True,
                    git_commits=[{"sha": "abc123", "message": "test", "author": "test"}],
                )

        # Success path: no "success" key, just check returned dict has expected fields
        assert "entry_id" in result
        assert "sequence_number" in result
        assert "message" in result
        # Verify the agent was decommissioned
        assert agent_working.status == "decommissioned"


class TestOrchestratorSelfDecommissionGuard:
    """Tests for the orchestrator self-decommission guard in close_project_and_update_memory.

    Handover 0824: When force=True is used, the guard prevents decommissioning
    an active orchestrator (which would lock it out of calling complete_job).
    """

    @pytest.mark.asyncio
    async def test_force_close_blocked_when_orchestrator_active(self):
        """Force-close must be blocked when the calling orchestrator is still active."""
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.tenant_key = tenant_key
        mock_project.product_id = product_id

        mock_product = MagicMock(spec=Product)
        mock_product.id = product_id
        mock_product.tenant_key = tenant_key
        mock_product.product_memory = {}

        orchestrator_agent = _make_execution(
            str(uuid4()),
            "orchestrator",
            status="working",
            job_id=str(uuid4()),
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            # TSK-9268: live action-required-unread query added at call 5.
            result.all.return_value = []
            if call_count["n"] == 1:
                # Project lookup
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                # Product lookup
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                # Readiness check -- orchestrator is working, not ready
                scalars = MagicMock()
                scalars.all.return_value = [orchestrator_agent]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                # Todo query for the orchestrator -- empty
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                # Orchestrator guard query -- finds the active orchestrator
                result.scalar_one_or_none.return_value = orchestrator_agent
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ProjectStateError) as exc_info:
            await close_project_and_update_memory(
                project_id=project_id,
                summary="Test summary",
                key_outcomes=["outcome-1"],
                decisions_made=["decision-1"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
                force=True,
            )

        assert exc_info.value.context["status"] == "ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED"
        # Must NOT have reached force decommission (call_count should be 6, not 7)
        assert call_count["n"] == 6

    @pytest.mark.asyncio
    async def test_force_close_allowed_when_only_specialists_active(self):
        """Force-close must proceed when only specialist (non-orchestrator) agents are active."""
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.tenant_key = tenant_key
        mock_project.product_id = product_id
        mock_project.created_at = datetime.now(UTC)
        mock_project.completed_at = None

        mock_project.name = "Test Project"

        mock_product = MagicMock(spec=Product)
        mock_product.id = product_id
        mock_product.tenant_key = tenant_key
        mock_product.product_memory = {}

        specialist_agent = _make_execution(
            str(uuid4()),
            "impl-1",
            status="working",
            job_id=str(uuid4()),
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            # TSK-9268: live action-required-unread query added at call 5.
            result.all.return_value = []
            if call_count["n"] == 1:
                # Project lookup
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                # Product lookup
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                # Readiness check -- specialist is working, not ready
                scalars = MagicMock()
                scalars.all.return_value = [specialist_agent]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                # Todo query for the specialist -- empty
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                # Orchestrator guard query -- no active orchestrator
                # (call 5 is the TSK-9268 live action-required-unread query)
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 7:
                # Force decommission query -- returns the specialist
                scalars = MagicMock()
                scalars.all.return_value = [specialist_agent]
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        mock_entry = MagicMock()
        mock_entry.id = str(uuid4())
        mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

        # BE-5022b: project_closeout now routes through ProductMemoryService
        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_repo_cls:
            repo_instance = mock_repo_cls.return_value
            repo_instance.get_next_sequence = AsyncMock(return_value=1)
            repo_instance.create_entry = AsyncMock(return_value=mock_entry)

            with patch(
                "giljo_mcp.tools.project_closeout.emit_websocket_event",
                new_callable=AsyncMock,
            ):
                result = await close_project_and_update_memory(
                    project_id=project_id,
                    summary="Test summary for specialist closeout",
                    key_outcomes=["outcome-1"],
                    decisions_made=["decision-1"],
                    tenant_key=tenant_key,
                    db_manager=mock_db_manager,
                    force=True,
                    git_commits=[{"sha": "abc123", "message": "test", "author": "test"}],
                )

        assert "entry_id" in result
        assert specialist_agent.status == "decommissioned"

    @pytest.mark.asyncio
    async def test_force_close_allowed_when_orchestrator_complete(self):
        """Force-close must proceed when orchestrator is already complete but specialists are stuck."""
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.tenant_key = tenant_key
        mock_project.product_id = product_id
        mock_project.created_at = datetime.now(UTC)
        mock_project.completed_at = None

        mock_project.name = "Test Project"

        mock_product = MagicMock(spec=Product)
        mock_product.id = product_id
        mock_product.tenant_key = tenant_key
        mock_product.product_memory = {}

        complete_orchestrator = _make_execution(
            str(uuid4()),
            "orchestrator",
            status="complete",
            job_id=str(uuid4()),
            tenant_key=tenant_key,
        )
        working_specialist = _make_execution(
            str(uuid4()),
            "impl-1",
            status="working",
            job_id=str(uuid4()),
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            # TSK-9268: live action-required-unread query added at call 5.
            result.all.return_value = []
            if call_count["n"] == 1:
                # Project lookup
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                # Product lookup
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                # Readiness exec scan -- both agents returned; specialist is working
                scalars = MagicMock()
                scalars.all.return_value = [complete_orchestrator, working_specialist]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                # BE-9144: the unified gathering now batches TODOs for every
                # non-skip agent into ONE WHERE job_id IN (...) query -- empty.
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                # Orchestrator guard query -- no active orchestrator (it is complete)
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 7:
                # Force decommission query -- returns the working specialist
                scalars = MagicMock()
                scalars.all.return_value = [working_specialist]
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        mock_entry = MagicMock()
        mock_entry.id = str(uuid4())
        mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

        # BE-5022b: project_closeout now routes through ProductMemoryService
        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_repo_cls:
            repo_instance = mock_repo_cls.return_value
            repo_instance.get_next_sequence = AsyncMock(return_value=1)
            repo_instance.create_entry = AsyncMock(return_value=mock_entry)

            with patch(
                "giljo_mcp.tools.project_closeout.emit_websocket_event",
                new_callable=AsyncMock,
            ):
                result = await close_project_and_update_memory(
                    project_id=project_id,
                    summary="Test summary for complete orchestrator",
                    key_outcomes=["outcome-1"],
                    decisions_made=["decision-1"],
                    tenant_key=tenant_key,
                    db_manager=mock_db_manager,
                    force=True,
                    git_commits=[{"sha": "abc123", "message": "test", "author": "test"}],
                )

        assert "entry_id" in result
        assert working_specialist.status == "decommissioned"
        # Orchestrator should remain complete, not touched
        assert complete_orchestrator.status == "complete"

    @pytest.mark.asyncio
    async def test_force_close_error_includes_orchestrator_job_id(self):
        """The ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED error must include the orchestrator's job_id."""
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"
        orch_job_id = str(uuid4())

        mock_project = MagicMock(spec=Project)
        mock_project.id = project_id
        mock_project.tenant_key = tenant_key
        mock_project.product_id = product_id

        mock_product = MagicMock(spec=Product)
        mock_product.id = product_id
        mock_product.tenant_key = tenant_key
        mock_product.product_memory = {}

        orchestrator_agent = _make_execution(
            str(uuid4()),
            "orchestrator",
            status="working",
            job_id=orch_job_id,
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}  # tenant_session_context save/restore target
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            # TSK-9268: live action-required-unread query added at call 5.
            result.all.return_value = []
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                scalars = MagicMock()
                scalars.all.return_value = [orchestrator_agent]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                result.scalar_one_or_none.return_value = orchestrator_agent
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ProjectStateError) as exc_info:
            await close_project_and_update_memory(
                project_id=project_id,
                summary="Test summary",
                key_outcomes=["outcome-1"],
                decisions_made=["decision-1"],
                tenant_key=tenant_key,
                db_manager=mock_db_manager,
                force=True,
            )

        # Verify the error context includes the orchestrator's job_id for remediation
        assert exc_info.value.context["status"] == "ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED"
        required_sequence = exc_info.value.context["required_sequence"]
        assert any(orch_job_id in step for step in required_sequence)
