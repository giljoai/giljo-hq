# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Pydantic validation models for ``Settings.settings_data`` category schemas.

Extracted from ``jsonb_validators.py`` (BE-9040 cleanup) to keep that module
under the 800-line file-size guardrail. These models are a cohesive unit: each
category-specific schema (``integrations``, ``security``) is
registered in ``SETTINGS_CATEGORY_VALIDATORS`` and validated at the
``SettingsService.update_settings`` write boundary via
``validate_settings_by_category``. Categories without a dedicated schema
(``general``, ``network``, ``database``) fall back to the generic
``SettingsData`` wrapper.

The names defined here are re-exported from ``jsonb_validators`` for backward
compatibility, so existing imports keep working unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# --- Settings.settings_data ---
# This is a per-category dict — categories are dynamic (general, network, database, etc.)
# We validate the wrapper structure, not internal category schemas


class SettingsData(BaseModel):
    """Validates settings.settings_data JSONB. Categories are dynamic."""

    model_config = ConfigDict(extra="allow")


# --- Settings category-specific validators (config.yaml -> DB migration) ---


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
    # Headless vs human-gated toggle. This model field's own default is NOT the
    # effective tenant default: that is resolved at the single read site in
    # SettingsService, not by this field. Read at the MCP launch gate.
    # Account/tenant-scoped (ADR-009).
    allow_headless_launch: bool = False
    # Marks whether this category's headless setting was set deliberately rather
    # than persisted incidentally by a full-model write. Does not affect how the
    # value above is read.
    allow_headless_launch_explicit: bool = False


# BE-9148: the ``runtime`` category (AgentRuntimeSettings/SessionRuntimeSettings/
# RuntimeSettingsData) was retired — it was seeded at boot and validated but had
# zero backend readers, no REST endpoint, and no frontend. A legacy ``runtime``
# settings row on an existing install is tolerated (never read; not enumerated by
# any category-listing path) and simply persists unused.


# --- Category-specific settings validators ---

# Map of category name -> validator model for SettingsService to use at write boundary
SETTINGS_CATEGORY_VALIDATORS: dict[str, type[BaseModel]] = {
    "integrations": IntegrationsSettingsData,
    "security": SecuritySettingsData,
}


def validate_settings_by_category(category: str, data: dict) -> dict:
    """Validate settings_data dict against category-specific Pydantic model.

    For categories without a specific validator (general, network, database),
    returns data as-is (validated by the generic SettingsData model).

    Args:
        category: Settings category name
        data: Raw settings data dict

    Returns:
        Validated and normalized dict

    Raises:
        pydantic.ValidationError: if data fails schema validation
    """
    validator_cls = SETTINGS_CATEGORY_VALIDATORS.get(category)
    if validator_cls is None:
        return SettingsData(**data).model_dump(exclude_none=False)
    return validator_cls(**data).model_dump(exclude_none=False)
