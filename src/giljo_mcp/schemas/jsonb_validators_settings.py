# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field




class SettingsData(BaseModel):
    """Validates settings.settings_data JSONB. Categories are dynamic."""

    model_config = ConfigDict(extra="allow")




class GitIntegrationSettings(BaseModel):
    """Validates git_integration block within integrations settings.

    BE-9103: ``max_commits`` was removed — commit depth is owned solely by the
    per-user Context-tab knob (UserFieldPriority ``git_history``), read by
    ``get_git_history``.

    BE-9148: ``include_commit_history`` and ``branch_strategy`` were retired —
    they were round-tripped through the git settings API but never consumed by
    the git-history fetch chain (only ``enabled`` gates fetch). As with
    ``max_commits``, a stale ``include_commit_history``/``branch_strategy``/
    ``max_commits`` key on an existing row is tolerated (Pydantic's default
    ``extra='ignore'`` drops it on the next write) and is never read.
    """

    enabled: bool = False
    use_in_prompts: bool = False


class SerenaMcpSettings(BaseModel):
    """Validates serena_mcp block within integrations settings."""

    use_in_prompts: bool = False


class IntegrationsSettingsData(BaseModel):
    """Validates settings.settings_data for category='integrations'."""

    git_integration: GitIntegrationSettings = Field(default_factory=GitIntegrationSettings)
    serena_mcp: SerenaMcpSettings = Field(default_factory=SerenaMcpSettings)


class SecuritySettingsData(BaseModel):
    """Validates settings.settings_data for category='security'.

    BE-9148: ``ssl_enabled``/``ssl_cert_path``/``ssl_key_path`` and the
    ``rate_limiting`` block were retired. SSL is owned by the file-based
    ConfigManager (``features.ssl_enabled`` + ``paths.ssl_*``, surfaced by
    ``get_ssl_enabled()``), and rate limiting by the env-configured limiter
    (``api/middleware/rate_limiter.py``); the DB-backed copies were validated
    and seeded but never read. Legacy ``ssl_*``/``rate_limiting`` keys on an
    existing security row are tolerated (Pydantic's default ``extra='ignore'``
    drops them on the next write) and are never read.
    """

    cookie_domain_whitelist: list[str] = Field(default_factory=list)
    allow_headless_launch: bool = False
    allow_headless_launch_explicit: bool = False





SETTINGS_CATEGORY_VALIDATORS: dict[str, type[BaseModel]] = {
    "integrations": IntegrationsSettingsData,
    "security": SecuritySettingsData,
}


def validate_settings_by_category(category: str, data: dict) -> dict:
    validator_cls = SETTINGS_CATEGORY_VALIDATORS.get(category)
    if validator_cls is None:
        return SettingsData(**data).model_dump(exclude_none=False)
    return validator_cls(**data).model_dump(exclude_none=False)
