# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Settings Service for Giljo HQ system settings management.

SettingsService handles CRUD operations for tenant-scoped settings (general, network, database).
Handover 0506: Settings endpoints implementation.
Updated Handover 0731: Reviewed for typed returns - dict[str, Any] retained because
settings are genuinely dynamic key-value pairs with user-configurable schemas that
vary by category and deployment. No fixed Pydantic model can represent the full range
of settings configurations.
"""

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
GLOBAL_GENERAL_SETTING_KEYS = {AGENT_SILENCE_THRESHOLD_KEY}
# FE-9241: shared upper bound for the SaaS per-tenant override (configurations
# table). CE's deployment-wide system_settings write path is intentionally left
# unbounded above (Field(ge=1) only) so this constant does NOT touch CE behavior.
MAX_AGENT_SILENCE_THRESHOLD_MINUTES = 1440

# INF-6049a: deployment-wide counter for the first-3-boots CE tool-rename notice
# (the get_orchestrator_instructions -> get_staging_instructions migration prompt).
TOOL_RENAME_BOOT_COUNT_KEY = "tool_rename_notice_boot_count"
# Surface the notice for this many CE process boots, then stop counting/showing.
TOOL_RENAME_NOTICE_MAX_BOOTS = 3


def _without_global_general_keys(settings_data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in settings_data.items() if key not in GLOBAL_GENERAL_SETTING_KEYS}


class SettingsService:
    """
    SettingsService - Manages tenant-scoped system settings.

    Supports categories: general, network, database, integrations, security, runtime.

    Args:
        session: AsyncSession - Database session
        tenant_key: str - Tenant identifier for multi-tenant isolation

    Methods:
        get_settings(category) - Get settings for category (returns {} if not found)
        get_setting_value(category, key, default) - Get single nested key from category
        update_settings(category, settings_data) - Upsert settings for category

    Raises:
        ValidationError if category is invalid or data fails schema validation
    """

    # BE-9148: "runtime" retired — it was seeded/validated but had zero readers,
    # no REST endpoint, and no frontend. A legacy "runtime" row on an existing
    # install is never read; get_settings/update_settings for it now raise the
    # standard invalid-category error (no caller relies on it).
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
        """
        Get settings for category.

        Args:
            category: Settings category (general, network, database, integrations, security)

        Returns:
            dict[str, Any] - Settings data (empty dict if not found).
            Intentionally returns dict because settings are dynamic key-value
            pairs with user-configurable schemas that vary by category.

        Raises:
            ValidationError: if category is invalid
        """
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
        """
        Get a single top-level key from a settings category.

        Convenience method for callers that only need one value (e.g., tools
        checking git_integration.enabled).

        Args:
            category: Settings category
            key: Top-level key within the settings_data dict
            default: Default value if key or category not found

        Returns:
            The value for the key, or default if not found.
        """
        data = await self.get_settings(category)
        return data.get(key, default)

    async def git_integration_enabled(self) -> bool:
        """Canonical read of the master Git + 360 Memory toggle (BE-9103).

        The SINGLE source of truth for whether git integration is on for this
        tenant: the Connect-tab toggle writes ``integrations.git_integration.enabled``
        via :func:`api.endpoints.git.toggle_git_integration`, and every consumer that
        gates commit instructions or serves git history reads THIS — never the legacy
        per-product ``product_memory.git_integration`` blob (which the current UI never
        writes, so it defaulted disabled forever). Read side only; no write.
        """
        git_settings = await self.get_setting_value("integrations", "git_integration", {})
        if not isinstance(git_settings, dict):
            return False
        return bool(git_settings.get("enabled", False))

    async def update_settings(self, category: str, settings_data: dict[str, Any]) -> dict[str, Any]:
        """
        Update settings for category (upsert).

        Validates settings_data against category-specific JSONB schema
        before persisting. For categories with known schemas (integrations,
        security), strict validation is applied. For others
        (general, network, database), the generic SettingsData validator is used.

        Args:
            category: Settings category
            settings_data: dict[str, Any] - Settings to save

        Returns:
            dict[str, Any] - Validated and updated settings data.

        Raises:
            ValidationError: if category is invalid or data fails schema validation
        """
        if category not in self.VALID_CATEGORIES:
            raise ValidationError(f"Invalid category: {category}. Must be one of {self.VALID_CATEGORIES}")

        # JSONB validation at write boundary (post-0962 discipline)
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
    """Manages deployment-wide settings stored in system_settings."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_agent_silence_threshold_minutes(self) -> int | None:
        result = await self.session.execute(
            select(SystemSetting.value).where(SystemSetting.key == AGENT_SILENCE_THRESHOLD_KEY)
        )
        value = result.scalar_one_or_none()

        if value is None:
            return None

        try:
            return max(1, int(value))
        except ValueError:
            return None

    async def update_agent_silence_threshold_minutes(self, minutes: int) -> int:
        if type(minutes) is not int or minutes < 1:
            raise ValidationError("agent_silence_threshold_minutes must be an integer greater than or equal to 1")

        value = str(minutes)
        result = await self.session.execute(
            select(SystemSetting).where(SystemSetting.key == AGENT_SILENCE_THRESHOLD_KEY)
        )
        setting = result.scalar_one_or_none()

        if setting is None:
            setting = SystemSetting(key=AGENT_SILENCE_THRESHOLD_KEY, value=value)
            self.session.add(setting)
        else:
            setting.value = value

        await self.session.commit()
        return minutes

    async def get_tool_rename_boot_count(self) -> int:
        """Return the deployment-wide tool-rename-notice boot count (0 if unset)."""
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
        """Bump the tool-rename-notice boot counter by one and return the new value.

        MUST be called exactly ONCE per process startup (not per banner-emit
        cycle), so the "first 3 boots" window counts boots rather than
        update-checker ticks. Saturates one past the notice window
        (``MAX_BOOTS + 1``) so it never grows unbounded after the notice retires.
        """
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
            # Already past the window — stop counting (no unbounded growth).
            return current

        new_value = current + 1
        if setting is None:
            setting = SystemSetting(key=TOOL_RENAME_BOOT_COUNT_KEY, value=str(new_value))
            self.session.add(setting)
        else:
            setting.value = str(new_value)

        await self.session.commit()
        return new_value


class TenantSkillsAckService:
    """Tenant-scoped read/write for the skills-bundle acknowledgement row.

    The single validated write path for ``tenant_skills_ack``. ``/giljo_setup``
    calls :meth:`acknowledge` with the server's bundled ``SKILLS_VERSION``; the
    skills-drift banner reads :meth:`get_acknowledged_version` to decide whether
    THIS tenant is behind. Every query is scoped to ``self.tenant_key`` via
    ``tenant_session_context`` (the guard injects the ``WHERE tenant_key = ?``
    filter), so no caller can read or write another tenant's row.
    """

    def __init__(self, session: AsyncSession, tenant_key: str):
        self.session = session
        self.tenant_key = tenant_key

    async def get_acknowledged_version(self) -> str | None:
        """Return the version this tenant last acknowledged, or None if never."""
        with tenant_session_context(self.session, self.tenant_key):
            result = await self.session.execute(
                select(TenantSkillsAck.acknowledged_version).where(TenantSkillsAck.tenant_key == self.tenant_key)
            )
            return result.scalar_one_or_none()

    async def acknowledge(self, version: str) -> str:
        """Upsert this tenant's acknowledged skills version (single write path).

        Args:
            version: the server's bundled ``SKILLS_VERSION`` the tenant just
                installed via ``/giljo_setup``.

        Returns:
            The acknowledged version persisted for the tenant.

        Raises:
            ValidationError: if ``version`` is not a non-empty string within the
                column length (untrusted-input guard; clean 422, not a DB 500).
        """
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
