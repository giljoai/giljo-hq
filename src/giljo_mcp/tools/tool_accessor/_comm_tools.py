# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any


class CommToolsMixin:

    async def join_thread(
        self,
        thread_id: str,
        agent_id: str,
        display_name: str | None = None,
        role: str | None = None,
        detected_harness: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        return await self._comm_thread_service.join_thread(
            thread_id=thread_id,
            participant_id=agent_id,
            participant_type="agent",
            display_name=display_name,
            role=role,
            detected_harness=detected_harness,
            tenant_key=tenant_key,
        )
