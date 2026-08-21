# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Job lifecycle adapter tools mixin for ToolAccessor (BE-6042a split).

BE-6118: the pure spawn_job / get_staging_instructions / get_job_mission /
update_job_mission / get_workflow_status / get_pending_jobs / report_progress /
complete_job / close_job / reactivate_job / dismiss_reactivation pass-throughs
were deleted (``_call_tool`` dispatches them straight to their terminal service
via ``TOOL_DISPATCH``). Only the two ADAPTER methods remain — ``get_agent_result``
(reshapes a ``None`` result into a message envelope) and ``set_agent_status``
(absorbs extra ``**kwargs``) — resolved through ``_call_tool``'s ``getattr``
fallback.
"""

from __future__ import annotations

from typing import Any


class JobLifecycleMixin:
    """get_agent_result + set_agent_status adapter tools. Composed into ToolAccessor."""

    async def get_agent_result(self, job_id: str, tenant_key: str) -> dict[str, Any]:
        """Fetch completion result for a completed agent job (delegates to OrchestrationService). Handover 0497e."""
        result = await self._orchestration_service.get_agent_result(job_id=job_id, tenant_key=tenant_key)
        if result is None:
            return {"result": None, "message": "No completion result found for this job"}
        return {"result": result}

    async def set_agent_status(
        self,
        job_id: str,
        status: str,
        reason: str = "",
        wake_in_minutes: int | None = None,
        tenant_key: str | None = None,
        wake_on_signal: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Set agent resting/blocked status. Sprint 002f: collapsed to AgentStateService."""
        return await self._agent_state_service.set_agent_status(
            job_id=job_id,
            status=status,
            reason=reason,
            wake_in_minutes=wake_in_minutes,
            wake_on_signal=wake_on_signal,
            tenant_key=tenant_key,
        )
