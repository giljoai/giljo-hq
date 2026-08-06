# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain-hub discovery at the service boundary (BE-9291).

The owning-service half of the FK-based hub lookup; the query and its precedence rule
live in ``repositories/_comm_thread_chain_hub_mixin``.

Lives in its own module rather than on ``CommThreadService`` because that module is
pinned at a shrink-only size budget — the same reason ``comm_serializers``,
``comm_author_identity`` and the edit/soft-delete mixins were split out. Mixed into
``CommThreadService``, so it uses that class's session/tenant plumbing
(``_resolve_tenant``, ``_scoped_session``) and the public API is unchanged.

Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.schemas.comm_serializers import thread_dict


# Mirrors the ``comm_threads.sequence_run_id`` column width. Enforced here at the
# owning service so the lookup never receives unbounded agent input — the value
# reaches an ILIKE in the legacy-fallback branch, and an unbounded one has no
# business getting that far.
_RUN_ID_MAX = 36


class CommThreadChainHubMixin:
    """Resolve a chain run's coordination hub. Mixed into CommThreadService."""

    async def resolve_chain_hub_thread(
        self, *, sequence_run_id: str, tenant_key: str | None = None
    ) -> dict[str, Any] | None:
        """Return THE hub thread of a chain run, or ``None`` if it has none.

        This is the structural replacement for ``search_threads(query="{run_id}")``.
        A sub-orchestrator no longer has to know that the run_id was spelled into the
        subject — it asks for its run's hub and gets it, or gets a clean ``None``.

        ``None`` rather than a raise is the right shape here, and deliberately so: a
        run legitimately has no hub (a solo run, or a chain whose conductor has not
        reached step 0 yet), and callers compose this into context payloads where an
        exception would take the whole read down over an ordinary absence.
        """
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
