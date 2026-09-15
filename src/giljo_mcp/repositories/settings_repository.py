# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.settings import Settings


logger = logging.getLogger(__name__)


class SettingsRepository:

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def get_by_category(
        self,
        session: AsyncSession,
        tenant_key: str,
        category: str,
    ) -> Settings | None:
        stmt = select(Settings).where(and_(Settings.tenant_key == tenant_key, Settings.category == category))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, session: AsyncSession, settings: Settings) -> None:
        session.add(settings)

    async def refresh(self, session: AsyncSession, entity) -> None:
        await session.refresh(entity)
