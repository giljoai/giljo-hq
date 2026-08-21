# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TenantConfigurationService - Service for DB-stored tenant configuration.

Sprint 003c: Extracted from api/endpoints/configuration.py to enforce
write discipline (no direct session.commit in endpoints).

This handles the Configuration model (DB rows), NOT config.yaml.
For YAML config, see ConfigService.
"""

import logging
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


logger = logging.getLogger(__name__)


class TenantConfigurationService:
    """
    Service for managing DB-stored tenant configurations.

    Wraps ConfigurationRepository with session management and commit control.
    All writes go through this service — endpoints never commit directly.
    """

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
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        """Get a session, preferring an injected test session when provided."""
        if self._session is not None:

            @asynccontextmanager
            async def _test_session_wrapper():
                yield self._session

            return _test_session_wrapper()

        return self.db_manager.get_session_async()

    async def execute_health_check(self) -> bool:
        """Execute a database health check query.

        BE-5022b: Service wrapper for ConfigurationRepository.execute_health_check().

        Returns:
            True if the database is healthy
        """
        async with self._get_session() as session:
            return await self._repo.execute_health_check(session)

    async def get_agent_silence_threshold_minutes(self) -> int | None:
        """Return this tenant's per-tenant silence-threshold override, or None if unset.

        FE-9241 (SaaS expansion): a per-tenant override stored in `configurations`
        (key="agent_silence_threshold_minutes"). CE never writes this row — CE's
        deployment-wide threshold lives in `system_settings` via
        SystemSettingsService, read separately by callers.

        Returns:
            The tenant's override in minutes, or None if this tenant has no
            override row (caller falls back to the deployment-wide default).
        """
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
        """Upsert this tenant's per-tenant silence-threshold override.

        Single write path: ConfigurationRepository.upsert_value (INSERT ... ON
        CONFLICT), tenant-scoped by self.tenant_key (ADR-009).

        Args:
            minutes: New threshold in minutes.

        Returns:
            The persisted threshold in minutes.

        Raises:
            ValidationError: if minutes is not an int in [1, MAX_AGENT_SILENCE_THRESHOLD_MINUTES]
                (untrusted agent/API input — clean 4xx, not a DB constraint 500).
        """
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
        """Return this tenant's per-tenant check-in cadence override, or None if unset.

        FE-9296b: the account-level agent check-in cadence, hosted exactly like the
        silence threshold above — SaaS writes a per-tenant `configurations` row; CE's
        deployment-wide value lives in `system_settings` via SystemSettingsService.
        """
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
        """Upsert this tenant's per-tenant check-in cadence override.

        Same write discipline as the silence threshold: single validated path,
        tenant-scoped by self.tenant_key (ADR-009).

        Raises:
            ValidationError: if minutes is not an int in [1, MAX_AGENT_CHECKIN_CADENCE_MINUTES]
                (untrusted agent/API input — clean 4xx, not a DB constraint 500).
        """
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
