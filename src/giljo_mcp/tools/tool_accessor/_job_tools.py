# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any


class JobLifecycleMixin:

    async def get_agent_result(self, job_id: str, tenant_key: str) -> dict[str, Any]:
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
        return await self._agent_state_service.set_agent_status(
            job_id=job_id,
            status=status,
            reason=reason,
            wake_in_minutes=wake_in_minutes,
            wake_on_signal=wake_on_signal,
            tenant_key=tenant_key,
        )
