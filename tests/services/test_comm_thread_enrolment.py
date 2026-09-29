# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.comm_thread_enrolment import resolve_and_enrol


pytestmark = pytest.mark.asyncio

_TENANT = "tk_tsk9459_enrolment"
_THREAD = "thread-uuid-9459"


def _job(job_type: str, *, project: bool = True) -> AgentJob:
    return AgentJob(
        job_id=str(uuid4()),
        tenant_key=_TENANT,
        project_id=str(uuid4()) if project else None,
        mission="m",
        job_type=job_type,
        status="active",
    )


def _execution() -> AgentExecution:
    return AgentExecution(
        agent_id=str(uuid4()),
        job_id=str(uuid4()),
        tenant_key=_TENANT,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="waiting",
    )


def _mission_service(thread_id: str | None = _THREAD) -> MagicMock:
    service = MagicMock()
    thread = {"thread_id": thread_id, "chat_id": "CHT-9459"} if thread_id else None
    service._resolve_comm_thread = AsyncMock(return_value=thread)
    return service


async def _run(job: AgentJob, thread_id: str | None = _THREAD):
    with patch("giljo_mcp.services.comm_thread_service.CommThreadService") as cls:
        cls.return_value.join_thread = AsyncMock(return_value={})
        result = await resolve_and_enrol(_mission_service(thread_id), MagicMock(), job, _execution(), _TENANT)
        return result, cls.return_value.join_thread


class TestWhoGetsEnrolled:
    async def test_an_orchestrator_is_enrolled(self):
        result, join = await _run(_job("orchestrator"))
        assert result["thread_id"] == _THREAD
        join.assert_awaited_once()
        assert join.await_args.kwargs["thread_id"] == _THREAD

    async def test_a_worker_is_not_enrolled_here(self):
        result, join = await _run(_job("implementer"))
        assert result["thread_id"] == _THREAD, "the worker still gets its thread id for the render"
        join.assert_not_awaited()

    async def test_an_unresolvable_thread_enrols_nobody(self):
        result, join = await _run(_job("orchestrator"), thread_id=None)
        assert result is None
        join.assert_not_awaited()


class TestProjectLessJob:
    async def test_resolves_nothing_and_never_queries(self):
        service = _mission_service()
        result = await resolve_and_enrol(
            service, MagicMock(), _job("orchestrator", project=False), _execution(), _TENANT
        )
        assert result is None
        service._resolve_comm_thread.assert_not_awaited()


class TestFailureNeverBreaksMissionDelivery:
    async def test_a_failed_join_still_returns_the_thread_id(self):
        with patch("giljo_mcp.services.comm_thread_service.CommThreadService") as cls:
            cls.return_value.join_thread = AsyncMock(side_effect=RuntimeError("hub down"))
            result = await resolve_and_enrol(
                _mission_service(), MagicMock(), _job("orchestrator"), _execution(), _TENANT
            )
        assert result["thread_id"] == _THREAD, "a Hub failure must not cost the agent its mission"
