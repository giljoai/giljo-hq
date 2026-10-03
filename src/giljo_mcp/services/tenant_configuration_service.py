# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.repositories.configuration_repository import ConfigurationRepository
from giljo_mcp.services.settings_service import (
    AGENT_CHECKIN_CADENCE_KEY,
    AGENT_SILENCE_THRESHOLD_KEY,
    MAX_AGENT_CHECKIN_CADENCE_MINUTES,
    MAX_AGENT_SILENCE_THRESHOLD_MINUTES,
)


class TenantConfigurationService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._session = session
        self._repo = ConfigurationRepository(db_manager)

    def _get_session(self):
        if self._session is not None:

            @asynccontextmanager
            async def _test_session_wrapper():
                yield self._session

            return _test_session_wrapper()

        return self.db_manager.get_session_async()

    async def execute_health_check(self) -> bool:
        async with self._get_session() as session:
            return await self._repo.execute_health_check(session)

    async def get_agent_silence_threshold_minutes(self) -> int | None:
        async with self._get_session() as session:
            raw = await self._repo.get_value(session, self.tenant_key, AGENT_SILENCE_THRESHOLD_KEY)

        if raw is None:
            return None
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            return None
        return minutes if 1 <= minutes <= MAX_AGENT_SILENCE_THRESHOLD_MINUTES else None

    async def set_agent_silence_threshold_minutes(self, minutes: int) -> int:
        if type(minutes) is not int or not (1 <= minutes <= MAX_AGENT_SILENCE_THRESHOLD_MINUTES):
            raise ValidationError(
                "agent_silence_threshold_minutes must be an integer between 1 and "
                f"{MAX_AGENT_SILENCE_THRESHOLD_MINUTES}"
            )

        async with self._get_session() as session:
            await self._repo.upsert_value(
                session,
                self.tenant_key,
                AGENT_SILENCE_THRESHOLD_KEY,
                minutes,
                category="system",
            )
            await session.commit()

        return minutes

    async def get_agent_checkin_cadence_minutes(self) -> int | None:
        async with self._get_session() as session:
            raw = await self._repo.get_value(session, self.tenant_key, AGENT_CHECKIN_CADENCE_KEY)

        if raw is None:
            return None
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            return None
        return minutes if 1 <= minutes <= MAX_AGENT_CHECKIN_CADENCE_MINUTES else None

    async def set_agent_checkin_cadence_minutes(self, minutes: int) -> int:
        if type(minutes) is not int or not (1 <= minutes <= MAX_AGENT_CHECKIN_CADENCE_MINUTES):
            raise ValidationError(
                f"agent_checkin_cadence_minutes must be an integer between 1 and {MAX_AGENT_CHECKIN_CADENCE_MINUTES}"
            )

        async with self._get_session() as session:
            await self._repo.upsert_value(
                session,
                self.tenant_key,
                AGENT_CHECKIN_CADENCE_KEY,
                minutes,
                category="system",
            )
            await session.commit()

        return minutes
