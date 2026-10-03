# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.config.defaults import DEFAULT_CATEGORY_TOGGLES, DEFAULT_DEPTH_CONFIG
from giljo_mcp.config.defaults import DEFAULT_FIELD_PRIORITY as _DEFAULT_FIELD_PRIORITY
from giljo_mcp.repositories.user_repository import UserRepository


logger = logging.getLogger(__name__)


DEFAULT_FIELD_PRIORITIES = _DEFAULT_FIELD_PRIORITY["priorities"]


def _normalize_field_toggles(field_config: dict[str, Any]) -> dict[str, bool]:
    normalized = {}
    for field_key, value in field_config.items():
        if isinstance(value, dict):
            normalized[field_key] = value.get("toggle", True)
        elif isinstance(value, bool):
            normalized[field_key] = value
        elif isinstance(value, int):
            normalized[field_key] = value < 4
        else:
            normalized[field_key] = True
    return normalized


async def _get_user_config(
    user_id: str,
    tenant_key: str,
    session: Any,
) -> dict[str, Any]:
    repo = UserRepository()

    try:
        user = await repo.get_user_by_id(session, user_id, tenant_key)

        if not user or not user.is_active:
            logger.warning(
                "user_not_found_using_defaults",
                extra={"user_id": user_id, "tenant_key": tenant_key},
            )
            normalized_defaults = _normalize_field_toggles(DEFAULT_FIELD_PRIORITIES.copy())
            return {"field_toggles": normalized_defaults, "depth_config": DEFAULT_DEPTH_CONFIG.copy()}

        rows = await repo.get_field_priorities(session, user_id, tenant_key)

        if rows:
            field_toggles = dict(DEFAULT_CATEGORY_TOGGLES)
            for row in rows:
                field_toggles[row.category] = row.enabled
            field_toggles["product_core"] = True
            field_toggles["project_description"] = True
        else:
            field_toggles = _normalize_field_toggles(DEFAULT_FIELD_PRIORITIES.copy())

        key_mapping = {
            "memory_last_n_projects": "memory_360",
            "git_commits": "git_history",
            "vision_documents": "vision_documents",
        }

        raw_depth = {
            "vision_documents": user.depth_vision_documents,
            "memory_last_n_projects": user.depth_memory_last_n,
            "git_commits": user.depth_git_commits,
            "tech_stack_sections": user.depth_tech_stack_sections,
            "architecture_depth": user.depth_architecture,
        }

        depth_config = {}
        for db_key, value in raw_depth.items():
            internal_key = key_mapping.get(db_key, db_key)
            depth_config[internal_key] = value

        if depth_config.get("vision_documents") == "optional":
            depth_config["vision_documents"] = "light"

        logger.info(
            "[USER_CONFIG] Fetched user configuration",
            extra={
                "user_id": user_id,
                "tenant_key": tenant_key,
                "depth_config": depth_config,
            },
        )

        return {"field_toggles": field_toggles, "depth_config": depth_config}

    except (OSError, ValueError, KeyError) as e:
        logger.error(
            "user_config_fetch_failed",
            extra={"user_id": user_id, "tenant_key": tenant_key, "error_message": str(e)},
            exc_info=True,
        )
        normalized_defaults = _normalize_field_toggles(DEFAULT_FIELD_PRIORITIES.copy())
        return {"field_toggles": normalized_defaults, "depth_config": DEFAULT_DEPTH_CONFIG.copy()}
