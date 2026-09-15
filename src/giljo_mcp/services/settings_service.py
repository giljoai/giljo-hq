# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any, ClassVar

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.settings import Settings
from giljo_mcp.models.system_setting import SystemSetting
from giljo_mcp.models.tenant_skills_ack import TenantSkillsAck
from giljo_mcp.repositories.settings_repository import SettingsRepository
from giljo_mcp.schemas.jsonb_validators import validate_settings_by_category


logger = logging.getLogger(__name__)

AGENT_SILENCE_THRESHOLD_KEY = "agent_silence_threshold_minutes"
AGENT_CHECKIN_CADENCE_KEY = "agent_checkin_cadence_minutes"
GLOBAL_GENERAL_SETTING_KEYS = {AGENT_SILENCE_THRESHOLD_KEY, AGENT_CHECKIN_CADENCE_KEY}
MAX_AGENT_SILENCE_THRESHOLD_MINUTES = 1440
MAX_AGENT_CHECKIN_CADENCE_MINUTES = 1440
DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES = 10

TOOL_RENAME_BOOT_COUNT_KEY = "tool_rename_notice_boot_count"
TOOL_RENAME_NOTICE_MAX_BOOTS = 3


def _without_global_general_keys(settings_data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in settings_data.items() if key not in GLOBAL_GENERAL_SETTING_KEYS}


class SettingsService:

    VALID_CATEGORIES: ClassVar[set[str]] = {
        "general",
        "network",
        "database",
        "integrations",
        "security",
    }

    def __init__(self, session: AsyncSession, tenant_key: str):
        self.session = session
        self.tenant_key = tenant_key
        self._repo = SettingsRepository()

    async def get_settings(self, category: str) -> dict[str, Any]:
        if category not in self.VALID_CATEGORIES:
            raise ValidationError(f"Invalid category: {category}. Must be one of {self.VALID_CATEGORIES}")

        with tenant_session_context(self.session, self.tenant_key):
            settings = await self._repo.get_by_category(self.session, self.tenant_key, category)

        if not settings:
            return {}

        settings_data = settings.settings_data or {}
        if category == "general":
            return _without_global_general_keys(settings_data)
        return settings_data

    async def get_setting_value(self, category: str, key: str, default: Any = None) -> Any:
        data = await self.get_settings(category)
        return data.get(key, default)

    async def git_integration_enabled(self) -> bool:
        git_settings = await self.get_setting_value("integrations", "git_integration", {})
        if not isinstance(git_settings, dict):
            return False
        return bool(git_settings.get("enabled", False))

    async def update_settings(self, category: str, settings_data: dict[str, Any]) -> dict[str, Any]:
        if category not in self.VALID_CATEGORIES:
            raise ValidationError(f"Invalid category: {category}. Must be one of {self.VALID_CATEGORIES}")

        try:
            validated_data = validate_settings_by_category(category, settings_data)
        except PydanticValidationError as e:
            raise ValidationError(f"Settings validation failed for category '{category}': {e}") from e

        if category == "general":
            validated_data = _without_global_general_keys(validated_data)

        with tenant_session_context(self.session, self.tenant_key):
            settings = await self._repo.get_by_category(self.session, self.tenant_key, category)

            if settings:
                settings.settings_data = validated_data
            else:
                settings = Settings(tenant_key=self.tenant_key, category=category, settings_data=validated_data)
                await self._repo.add(self.session, settings)

            await self.session.commit()
            await self._repo.refresh(self.session, settings)

        return settings.settings_data


class SystemSettingsService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_minutes_setting(self, key: str) -> int | None:
        result = await self.session.execute(select(SystemSetting.value).where(SystemSetting.key == key))
        value = result.scalar_one_or_none()

        if value is None:
            return None

        try:
            return max(1, int(value))
        except ValueError:
            return None

    async def _update_minutes_setting(self, key: str, minutes: int) -> int:
        if type(minutes) is not int or minutes < 1:
            raise ValidationError(f"{key} must be an integer greater than or equal to 1")

        value = str(minutes)
        result = await self.session.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()

        if setting is None:
            setting = SystemSetting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value

        await self.session.commit()
        return minutes

    async def get_agent_silence_threshold_minutes(self) -> int | None:
        return await self._get_minutes_setting(AGENT_SILENCE_THRESHOLD_KEY)

    async def update_agent_silence_threshold_minutes(self, minutes: int) -> int:
        return await self._update_minutes_setting(AGENT_SILENCE_THRESHOLD_KEY, minutes)

    async def get_agent_checkin_cadence_minutes(self) -> int | None:
        return await self._get_minutes_setting(AGENT_CHECKIN_CADENCE_KEY)

    async def update_agent_checkin_cadence_minutes(self, minutes: int) -> int:
        return await self._update_minutes_setting(AGENT_CHECKIN_CADENCE_KEY, minutes)

    async def get_tool_rename_boot_count(self) -> int:
        result = await self.session.execute(
            select(SystemSetting.value).where(SystemSetting.key == TOOL_RENAME_BOOT_COUNT_KEY)
        )
        value = result.scalar_one_or_none()
        if value is None:
            return 0
        try:
            return max(0, int(value))
        except ValueError:
            return 0

    async def increment_tool_rename_boot_count(self) -> int:
        result = await self.session.execute(
            select(SystemSetting).where(SystemSetting.key == TOOL_RENAME_BOOT_COUNT_KEY)
        )
        setting = result.scalar_one_or_none()

        current = 0
        if setting is not None:
            try:
                current = max(0, int(setting.value))
            except ValueError:
                current = 0

        if current > TOOL_RENAME_NOTICE_MAX_BOOTS:
            return current

        new_value = current + 1
        if setting is None:
            setting = SystemSetting(key=TOOL_RENAME_BOOT_COUNT_KEY, value=str(new_value))
            self.session.add(setting)
        else:
            setting.value = str(new_value)

        await self.session.commit()
        return new_value


async def resolve_agent_checkin_cadence_minutes(
    session: AsyncSession,
    tenant_key: str | None = None,
    project: Any = None,
) -> int:
    if project is not None and getattr(project, "auto_checkin_enabled", False):
        interval = getattr(project, "auto_checkin_interval", None)
        if type(interval) is int and interval >= 1:
            return interval

    if tenant_key:
        from giljo_mcp.repositories.configuration_repository import ConfigurationRepository

        raw = await ConfigurationRepository(None).get_value(session, tenant_key, AGENT_CHECKIN_CADENCE_KEY)
        if raw is not None and not isinstance(raw, bool):
            try:
                minutes = int(raw)
            except (TypeError, ValueError, OverflowError):
                minutes = None
            if minutes is not None and 1 <= minutes <= MAX_AGENT_CHECKIN_CADENCE_MINUTES:
                return minutes

    deployment_default = await SystemSettingsService(session).get_agent_checkin_cadence_minutes()
    return deployment_default or DEFAULT_AGENT_CHECKIN_CADENCE_MINUTES


async def resolve_checkin_cadence_safe(
    session: AsyncSession,
    tenant_key: str | None = None,
    project: Any = None,
) -> int | None:
    try:
        return await resolve_agent_checkin_cadence_minutes(session, tenant_key, project)
    except Exception:  # noqa: BLE001
        logger.warning("[FE-9296b] check-in cadence resolution failed; caller falls back")
        return None


async def load_integrations_and_cadence(get_session, tenant_key: str, project: Any = None) -> tuple[dict, int | None]:
    integrations: dict = {}
    cadence: int | None = None
    try:
        async with get_session(tenant_key) as session:
            integrations = await SettingsService(session, tenant_key).get_settings("integrations")
            cadence = await resolve_checkin_cadence_safe(session, tenant_key, project)
    except Exception:  # noqa: BLE001
        logger.warning("[INTEGRATIONS] Failed to read settings from DB")
    return integrations, cadence


class TenantSkillsAckService:

    def __init__(self, session: AsyncSession, tenant_key: str):
        self.session = session
        self.tenant_key = tenant_key

    async def get_acknowledged_version(self) -> str | None:
        with tenant_session_context(self.session, self.tenant_key):
            result = await self.session.execute(
                select(TenantSkillsAck.acknowledged_version).where(TenantSkillsAck.tenant_key == self.tenant_key)
            )
            return result.scalar_one_or_none()

    async def acknowledge(self, version: str) -> str:
        if not isinstance(version, str) or not version.strip():
            raise ValidationError("acknowledged skills version must be a non-empty string")
        version = version.strip()
        if len(version) > 128:
            raise ValidationError("acknowledged skills version must be at most 128 characters")

        with tenant_session_context(self.session, self.tenant_key):
            result = await self.session.execute(
                select(TenantSkillsAck).where(TenantSkillsAck.tenant_key == self.tenant_key)
            )
            row = result.scalar_one_or_none()

            if row is None:
                row = TenantSkillsAck(tenant_key=self.tenant_key, acknowledged_version=version)
                self.session.add(row)
            else:
                row.acknowledged_version = version

            await self.session.commit()

        return version
