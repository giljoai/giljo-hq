# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain-hub discovery for a sequence run (BE-9291).

Its own module for the same two reasons the enrichment mixin has one, and both are
real here too.

The concern is distinct. Everything else in ``CommThreadRepository`` is thread CRUD
and the baton/status queries the tool surface is built on. This is ONE lookup with a
precedence rule and a legacy-tolerance branch, and the rule needs more explanation
than the query needs code — inlining it would put a paragraph of chain-lifecycle
reasoning in the middle of the data foundation.

And the size budget forced the seam: ``comm_thread_service.py`` sits at a 817-line
SHRINK-ONLY budget with under twenty lines of headroom, so its half of this pairs with
``services/_comm_thread_chain_hub_mixin.py``. Inherited by ``CommThreadRepository`` on
the seam the directed-actions / list-enrichment / participants mixins established, so
the public repository API is unchanged.

Tenant-scoped.
Edition Scope: CE.
"""

from __future__ import annotations

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.sequence_runs import SequenceRun


class CommThreadChainHubMixin:
    """Resolve THE coordination hub of a chain run. Inherited by CommThreadRepository."""

    async def _require_sequence_run(self, session: AsyncSession, tenant_key: str, sequence_run_id: str) -> None:
        """Verify a run id names a real run IN THIS TENANT before it is stored.

        The FK constraint is not enough on its own. It would turn a typo into a 500
        instead of a 422, and — because ``sequence_runs.id`` is globally unique rather
        than tenant-qualified — it would happily accept ANOTHER tenant's run id and
        create a cross-tenant link. This is the tenant-scoped check that closes both
        (ADR-009: a run id is not a capability).
        """
        exists = (
            await session.execute(
                select(SequenceRun.id).where(
                    SequenceRun.tenant_key == tenant_key,
                    SequenceRun.id == sequence_run_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise ValidationError(
                "sequence_run_id does not name a chain run in this workspace",
                context={"operation": "comm_thread.create", "sequence_run_id": sequence_run_id},
            )

    async def _require_run_is_unhubbed(self, session: AsyncSession, tenant_key: str, sequence_run_id: str) -> None:
        """Refuse to stamp a run that already has a LIVE hub, and name the one it has.

        A run has exactly one coordination hub. Nothing structural enforced that:
        ``idx_comm_thread_sequence_run`` is a plain index rather than a unique one, so
        a second thread could take the same link. Both would then land in the FK branch
        of ``resolve_chain_hub_thread``'s CASE, the authoritative branch would stop
        discriminating, and ``created_at`` ascending would decide -- answering with
        whichever thread is older rather than with the hub, and raising nothing.

        The path there needs no misbehaviour, only a retry. A conductor whose
        ``create_thread`` succeeds at chain staging step 0 but which dies or is
        restaged before it records the thread id re-runs step 0, creates a SECOND hub,
        and hands that one to its sub-orchestrators. From then on the chain context
        answers every sub-orchestrator with the first, abandoned thread while the
        conductor polls the second: split-brain coordination, silently.

        So the refusal NAMES the existing hub. A restaged conductor's correct move is
        to adopt the hub its predecessor created, and an error that only said "no"
        would leave it stranded -- moving the failure rather than removing it.

        A SOFT-DELETED hub does not block: it is already invisible to resolution, so a
        replacement is legitimate rather than a collision. Tenant-scoped, like every
        other query on this seam.
        """
        existing = (
            (
                await session.execute(
                    select(CommThread.id).where(
                        CommThread.tenant_key == tenant_key,
                        CommThread.sequence_run_id == sequence_run_id,
                        CommThread.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise ValidationError(
                f"chain run {sequence_run_id} already has a coordination hub thread "
                f"({existing}) — post to that thread instead of creating a second hub",
                context={
                    "operation": "comm_thread.create",
                    "sequence_run_id": sequence_run_id,
                    "hub_thread_id": existing,
                },
            )

    async def resolve_chain_hub_thread(
        self, session: AsyncSession, tenant_key: str, sequence_run_id: str
    ) -> CommThread | None:
        """Find the hub thread for a chain run — by FK first, by subject only as a fallback.

        This is what replaced ``search_threads(query="{run_id}")``. That worked by
        substring-matching the run_id out of the thread's own SUBJECT, which made a
        free-text display field load-bearing lookup machinery. Its failure mode was
        silent: nothing raised, the sub-orchestrator just never found its hub.

        Precedence among LIVE (``deleted_at IS NULL``) threads in this tenant, modelled
        on ``resolve_or_create_bound_thread``:

          1. ``sequence_run_id == run`` -> that thread, whatever its subject says;
          2. otherwise a subject CONTAINING the run id -> the legacy convention;
          3. ties broken by OLDEST first, so the answer is stable across calls;
          4. no match -> ``None``, an explicit absence rather than a wrong thread.

        Branch 2 is deliberate and is not dead weight. It covers the two rows the FK
        cannot: a pre-``ce_0087`` hub whose subject named two runs (the backfill skips
        ambiguous matches by design), and a hub some future conductor creates without
        stamping the link. Keeping it is what makes dropping the run_id from new
        subjects safe — the old shape is TOLERATED, not required.

        The CASE order-by (not two queries) keeps this one round trip and makes the
        precedence a property of the statement rather than of call order.
        """
        if not sequence_run_id:
            raise ValidationError(
                "sequence_run_id is required",
                context={"operation": "comm_thread.resolve_chain_hub"},
            )
        linked = CommThread.sequence_run_id == sequence_run_id
        return (
            await session.execute(
                select(CommThread)
                .where(
                    CommThread.tenant_key == tenant_key,
                    CommThread.deleted_at.is_(None),
                    or_(linked, CommThread.subject.contains(sequence_run_id, autoescape=True)),
                )
                .order_by(case((linked, 0), else_=1), CommThread.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
