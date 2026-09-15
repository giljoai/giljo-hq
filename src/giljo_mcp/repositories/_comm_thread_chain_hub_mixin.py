# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.sequence_runs import SequenceRun


class CommThreadChainHubMixin:

    async def _require_sequence_run(self, session: AsyncSession, tenant_key: str, sequence_run_id: str) -> None:
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
