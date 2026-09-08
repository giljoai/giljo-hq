# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Repository for the user_approvals primitive (BE-5029 Phase A).

Every query MUST filter by ``tenant_key``. No exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.user_approval import UserApproval


class UserApprovalRepository:
    """CRUD for user_approvals with mandatory tenant isolation."""

    def __init__(self, db_manager):
        self.db = db_manager

    async def create(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        agent_execution_id: str,
        job_id: str,
        project_id: str,
        reason: str,
        options: list[dict],
        context: dict | None,
    ) -> UserApproval:
        approval = UserApproval(
            tenant_key=tenant_key,
            agent_execution_id=agent_execution_id,
            job_id=job_id,
            project_id=project_id,
            reason=reason,
            options=options,
            context=context,
            status="pending",
        )
        session.add(approval)
        await session.flush()
        return approval

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        approval_id: str,
    ) -> UserApproval | None:
        with tenant_session_context(session, tenant_key):
            result = await session.execute(
                select(UserApproval).where(
                    UserApproval.tenant_key == tenant_key,
                    UserApproval.id == approval_id,
                )
            )
        return result.scalar_one_or_none()

    async def list_pending_for_tenant(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        limit: int,
        offset: int,
        status: str = "pending",
    ) -> list[UserApproval]:
        """List approvals for a tenant by status, newest first.

        Backed by ``ix_user_approvals_tenant_status`` (tenant_key, status).
        ``status`` defaults to ``"pending"`` (the original/only caller shape);
        BE-9514 widened this to any status so a decided row's ``decided_via``
        can be read back for verification.
        """
        with tenant_session_context(session, tenant_key):
            result = await session.execute(
                select(UserApproval)
                .where(
                    UserApproval.tenant_key == tenant_key,
                    UserApproval.status == status,
                )
                .order_by(UserApproval.requested_at.desc())
                .limit(limit)
                .offset(offset)
            )
        return list(result.scalars().all())

    async def count_pending_for_tenant(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        status: str = "pending",
    ) -> int:
        from sqlalchemy import func

        with tenant_session_context(session, tenant_key):
            result = await session.execute(
                select(func.count(UserApproval.id)).where(
                    UserApproval.tenant_key == tenant_key,
                    UserApproval.status == status,
                )
            )
        return int(result.scalar_one() or 0)

    async def get_pending_for_agent(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        agent_execution_id: str,
    ) -> UserApproval | None:
        with tenant_session_context(session, tenant_key):
            result = await session.execute(
                select(UserApproval).where(
                    UserApproval.tenant_key == tenant_key,
                    UserApproval.agent_execution_id == agent_execution_id,
                    UserApproval.status == "pending",
                )
            )
        return result.scalar_one_or_none()

    async def mark_decided(
        self,
        session: AsyncSession,
        *,
        tenant_key: str,
        approval_id: str,
        decided_option_id: str,
        decided_by_user_id: str | None,
        decided_via: str,
    ) -> UserApproval | None:
        approval = await self.get_by_id(
            session,
            tenant_key=tenant_key,
            approval_id=approval_id,
        )
        if approval is None or approval.status != "pending":
            return None
        approval.status = "decided"
        approval.decided_option_id = decided_option_id
        approval.decided_by_user_id = decided_by_user_id
        approval.decided_via = decided_via
        approval.decided_at = datetime.now(UTC)
        await session.flush()
        return approval
