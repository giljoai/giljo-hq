# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from sqlalchemy import MetaData


ARTIFACT_SCHEMA_VERSION = "2.0"



EXPORT_EXCLUDE: frozenset[str] = frozenset(
    {
        "download_tokens",
        "email_change_tokens",
        "mcp_sessions",
        "oauth_authorization_codes",
        "password_reset_tokens",
        "api_keys",
        "oauth_clients",
        "oauth_refresh_tokens",
        "oauth_revoked_tokens",
        "org_api_keys",
        "account_deletion_requests",
        "organization_plans",
        "organization_terms_acceptances",
        "restore_requests",
        "tenant_trials",
        "api_metrics",
    }
)


def _tenant_mappers() -> dict[str, type]:
    import giljo_mcp.models  # noqa: F401 — registers all CE models on Base (side effect)
    from giljo_mcp.models.base import Base

    out: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table is not None and "tenant_key" in table.columns:
            out.setdefault(table.name, mapper.class_)
    return out


def capture_models() -> tuple[type, ...]:
    from giljo_mcp.models.base import Base

    mappers = _tenant_mappers()
    return tuple(
        mappers[table.name]
        for table in Base.metadata.sorted_tables
        if table.name in mappers and table.name not in EXPORT_EXCLUDE
    )


def capture_table_names() -> list[str]:
    return [model.__tablename__ for model in capture_models()]


def models_by_table() -> dict[str, type]:
    return {model.__tablename__: model for model in capture_models()}


def unaccounted_tenant_tables(metadata: MetaData | None = None) -> set[str]:
    captured = {model.__tablename__ for model in capture_models()}
    if metadata is None:
        from giljo_mcp.models.base import Base

        metadata = Base.metadata
    tenant_tables = {t.name for t in metadata.tables.values() if "tenant_key" in t.columns}
    return tenant_tables - captured - EXPORT_EXCLUDE
