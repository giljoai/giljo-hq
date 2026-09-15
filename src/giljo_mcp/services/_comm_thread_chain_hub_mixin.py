# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.schemas.comm_serializers import thread_dict


_RUN_ID_MAX = 36


class CommThreadChainHubMixin:

    async def resolve_chain_hub_thread(
        self, *, sequence_run_id: str, tenant_key: str | None = None
    ) -> dict[str, Any] | None:
        run_id = (sequence_run_id or "").strip()
        if not run_id:
            raise ValidationError(
                "sequence_run_id is required",
                context={"operation": "comm_thread.resolve_chain_hub"},
            )
        if len(run_id) > _RUN_ID_MAX:
            raise ValidationError(
                f"sequence_run_id must be at most {_RUN_ID_MAX} characters",
                context={"operation": "comm_thread.resolve_chain_hub"},
            )
        tk = self._resolve_tenant(tenant_key)
        async with self._scoped_session(tk) as session:
            thread = await self._repo.resolve_chain_hub_thread(session, tk, run_id)
            return thread_dict(thread) if thread is not None else None
