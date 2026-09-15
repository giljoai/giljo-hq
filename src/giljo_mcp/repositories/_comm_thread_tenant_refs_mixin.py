# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError


class CommThreadTenantRefsMixin:

    async def _require_owned_reference(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        model: type,
        row_id: str,
        field: str,
    ) -> None:
        owned = (
            await session.execute(select(model.id).where(model.tenant_key == tenant_key, model.id == row_id))
        ).scalar_one_or_none()
        if owned is None:
            raise ValidationError(
                f"{field} does not name a {model.__name__.lower()} in this workspace",
                context={"operation": "comm_thread.create", field: row_id},
            )
