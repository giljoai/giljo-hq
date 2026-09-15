# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ProjectStateError
from giljo_mcp.tools.project_closeout import (
    _check_agent_readiness,
    _force_decommission_agents,
    close_project_and_update_memory,
)
from tests.helpers.model_factories import make_agent_execution, make_product, make_project


def _make_execution(
    agent_id: str,
    display_name: str,
    status: str = "complete",
    job_id: str | None = None,
    tenant_key: str = "test-tenant",
    messages_waiting: int = 0,
) -> Mock:
    resolved_job_id = job_id or str(uuid4())
    return make_agent_execution(
        id=resolved_job_id,
        agent_id=agent_id,
        agent_display_name=display_name,
        agent_name=display_name,
        status=status,
        job_id=resolved_job_id,
        tenant_key=tenant_key,
        messages_waiting_count=messages_waiting,
        started_at=datetime.now(UTC),
    )


def _execute_then_empty(executions):
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

    @pytest.mark.asyncio
    async def test_all_complete_returns_ready(self):
        session = AsyncMock()
        project_id = str(uuid4())

        agent_a = _make_execution(str(uuid4()), "impl-1", "complete")
        agent_b = _make_execution(str(uuid4()), "analyzer-1", "complete")

        session.execute = AsyncMock(side_effect=_execute_then_empty([agent_a, agent_b]))

        is_ready, blockers = await _check_agent_readiness(session, project_id, "test-tenant")

        assert is_ready is True
        assert blockers == []

    @pytest.mark.asyncio
    async def test_active_agents_return_blockers(self):
        session = AsyncMock()
        project_id = str(uuid4())

        agent_a = _make_execution(str(uuid4()), "impl-1", "complete")
        agent_b = _make_execution(str(uuid4()), "ui-builder", "working")
        agent_c = _make_execution(str(uuid4()), "tester", "silent")

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = Mock()
            result.all.return_value = []
            if call_count["n"] == 1:
                scalars = Mock()
                scalars.all.return_value = [agent_a, agent_b, agent_c]
                result.scalars.return_value = scalars
            else:
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
        for b in agent_blockers:
            assert "issue_type" in b
            assert "suggested_action" in b
            assert b["issue_type"] == "still_working"

    @pytest.mark.asyncio
    async def test_decommissioned_agents_skipped(self):
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

    @pytest.mark.asyncio
    async def test_active_agents_decommissioned(self):
        session = AsyncMock()
        project_id = str(uuid4())

        agent_working = _make_execution(str(uuid4()), "ui-builder", "working")
        agent_silent = _make_execution(str(uuid4()), "tester", "silent")

        session.execute = AsyncMock(side_effect=_execute_then_empty([agent_working, agent_silent]))

        decommissioned = await _force_decommission_agents(session, project_id, "test-tenant")

        assert len(decommissioned) == 2
        assert agent_working.status == "decommissioned"
        assert agent_silent.status == "decommissioned"
        assert "ui-builder" in decommissioned
        assert "tester" in decommissioned
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_active_agents_returns_empty(self):
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

    @pytest.mark.asyncio
    async def test_blocked_when_agents_active_and_no_force(self):
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = make_project(id=project_id, tenant_key=tenant_key, product_id=product_id)

        mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

        agent_working = _make_execution(str(uuid4()), "impl-1", "working")

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            result.all.return_value = []
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                scalars = MagicMock()
                scalars.all.return_value = [agent_working]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

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
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = make_project(
            id=project_id,
            tenant_key=tenant_key,
            product_id=product_id,
            created_at=datetime.now(UTC),
            name="Test Project",
        )

        mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

        agent_working = _make_execution(str(uuid4()), "impl-1", "working")

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            result.all.return_value = []
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                scalars = MagicMock()
                scalars.all.return_value = [agent_working]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 7:
                scalars = MagicMock()
                scalars.all.return_value = [agent_working]
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        mock_entry = MagicMock()
        mock_entry.id = str(uuid4())
        mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_svc_cls:
            repo_instance = mock_svc_cls.return_value
            repo_instance.get_next_sequence = AsyncMock(return_value=1)
            repo_instance.get_closeout_entry_for_project = AsyncMock(return_value=None)
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

        assert "entry_id" in result
        assert "sequence_number" in result
        assert "message" in result
        assert agent_working.status == "decommissioned"


class TestOrchestratorSelfDecommissionGuard:

    @pytest.mark.asyncio
    async def test_force_close_blocked_when_orchestrator_active(self):
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = make_project(id=project_id, tenant_key=tenant_key, product_id=product_id)

        mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

        orchestrator_agent = _make_execution(
            str(uuid4()),
            "orchestrator",
            status="working",
            job_id=str(uuid4()),
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
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

        assert exc_info.value.context["status"] == "ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED"
        assert call_count["n"] == 6

    @pytest.mark.asyncio
    async def test_force_close_allowed_when_only_specialists_active(self):
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = make_project(
            id=project_id,
            tenant_key=tenant_key,
            product_id=product_id,
            created_at=datetime.now(UTC),
            name="Test Project",
        )

        mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

        specialist_agent = _make_execution(
            str(uuid4()),
            "impl-1",
            status="working",
            job_id=str(uuid4()),
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            result.all.return_value = []
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                scalars = MagicMock()
                scalars.all.return_value = [specialist_agent]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 7:
                scalars = MagicMock()
                scalars.all.return_value = [specialist_agent]
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        mock_entry = MagicMock()
        mock_entry.id = str(uuid4())
        mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_repo_cls:
            repo_instance = mock_repo_cls.return_value
            repo_instance.get_next_sequence = AsyncMock(return_value=1)
            repo_instance.get_closeout_entry_for_project = AsyncMock(return_value=None)
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
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"

        mock_project = make_project(
            id=project_id,
            tenant_key=tenant_key,
            product_id=product_id,
            created_at=datetime.now(UTC),
            name="Test Project",
        )

        mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

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
        mock_session.info = {}
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            result.all.return_value = []
            if call_count["n"] == 1:
                result.scalar_one_or_none.return_value = mock_project
            elif call_count["n"] == 2:
                result.scalar_one_or_none.return_value = mock_product
            elif call_count["n"] == 3:
                scalars = MagicMock()
                scalars.all.return_value = [complete_orchestrator, working_specialist]
                result.scalars.return_value = scalars
            elif call_count["n"] == 4:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count["n"] == 6:
                result.scalar_one_or_none.return_value = None
            elif call_count["n"] == 7:
                scalars = MagicMock()
                scalars.all.return_value = [working_specialist]
                result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        mock_entry = MagicMock()
        mock_entry.id = str(uuid4())
        mock_entry.to_dict.return_value = {"id": str(mock_entry.id)}

        with patch("giljo_mcp.tools.project_closeout.ProductMemoryService") as mock_repo_cls:
            repo_instance = mock_repo_cls.return_value
            repo_instance.get_next_sequence = AsyncMock(return_value=1)
            repo_instance.get_closeout_entry_for_project = AsyncMock(return_value=None)
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
        assert complete_orchestrator.status == "complete"

    @pytest.mark.asyncio
    async def test_force_close_error_includes_orchestrator_job_id(self):
        project_id = str(uuid4())
        product_id = str(uuid4())
        tenant_key = "test-tenant"
        orch_job_id = str(uuid4())

        mock_project = make_project(id=project_id, tenant_key=tenant_key, product_id=product_id)

        mock_product = make_product(id=product_id, tenant_key=tenant_key, product_memory={})

        orchestrator_agent = _make_execution(
            str(uuid4()),
            "orchestrator",
            status="working",
            job_id=orch_job_id,
            tenant_key=tenant_key,
        )

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_db_manager = MagicMock()
        mock_db_manager.get_session_async.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_manager.get_session_async.return_value.__aexit__ = AsyncMock(return_value=False)

        call_count = {"n": 0}

        async def mock_execute(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
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

        assert exc_info.value.context["status"] == "ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED"
        required_sequence = exc_info.value.context["required_sequence"]
        assert any(orch_job_id in step for step in required_sequence)
