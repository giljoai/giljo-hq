# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Agent Message Hub thread adapter tool for ToolAccessor (BE-6054b).

BE-6118: the pure create_thread / post_to_thread / get_my_turn / pass_baton /
list_threads / get_thread_history / search_threads pass-throughs were deleted
(``_call_tool`` dispatches them straight to CommThreadService via
``TOOL_DISPATCH``). Only ``join_thread`` stays — it is an ADAPTER that maps the
tool's ``agent_id`` onto the service's ``participant_id`` and injects
``participant_type="agent"``, so it is deliberately absent from the registry and
resolves through ``_call_tool``'s ``getattr`` fallback.
"""

from __future__ import annotations

from typing import Any


class CommToolsMixin:
    """Comm-thread (message board) join adapter. Composed into ToolAccessor."""

    async def join_thread(
        self,
        thread_id: str,
        agent_id: str,
        display_name: str | None = None,
        role: str | None = None,
        detected_harness: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        # BE-9289a: ``detected_harness`` is resolved at the MCP boundary from the
        # session clientInfo and passed straight through — the adapter never invents or
        # defaults it, so a caller that cannot be detected reaches the service as None
        # and the service applies the 'generic' floor in one place.
        return await self._comm_thread_service.join_thread(
            thread_id=thread_id,
            participant_id=agent_id,
            participant_type="agent",
            display_name=display_name,
            role=role,
            detected_harness=detected_harness,
            tenant_key=tenant_key,
        )
