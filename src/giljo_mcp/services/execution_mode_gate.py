# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.platform_registry import VALID_EXECUTION_MODES, mode_label_list


__all__ = [
    "EXECUTION_MODE_NOT_SELECTED_MESSAGE",
    "VALID_EXECUTION_MODES",
    "effective_execution_mode",
    "execution_mode_not_selected_message",
    "execution_mode_selected",
    "require_execution_mode",
]


def effective_execution_mode(project_execution_mode: Any, chain_execution_mode: Any = None) -> Any:
    chain_mode = str(chain_execution_mode).strip() if chain_execution_mode else ""
    return chain_mode or project_execution_mode


EXECUTION_MODE_NOT_SELECTED_MESSAGE = (
    "No execution mode is selected for this project. Open the project in the "
    f"GiljoAI dashboard, pick an execution mode ({mode_label_list()}), and stage "
    "it before continuing."
)


def execution_mode_not_selected_message(project_name: str | None = None) -> str:
    if not project_name:
        return EXECUTION_MODE_NOT_SELECTED_MESSAGE
    return EXECUTION_MODE_NOT_SELECTED_MESSAGE.replace("for this project.", f"for project '{project_name}'.", 1)


def execution_mode_selected(project: Any) -> bool:
    mode = getattr(project, "execution_mode", None)
    return bool(mode and str(mode).strip())


def require_execution_mode(project: Any, project_id: str, tenant_key: str) -> None:
    if not execution_mode_selected(project):
        raise ValidationError(
            message=execution_mode_not_selected_message(getattr(project, "name", None)),
            error_code="EXECUTION_MODE_NOT_SELECTED",
            context={"project_id": project_id, "tenant_key": tenant_key},
        )
