# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.platform_registry import EXECUTION_MODES, VALID_EXECUTION_MODES


STAGE_MODE_ASK = "ask"

EXECUTION_MODE_DEFAULT_KEY = "execution_mode_default"

EXECUTION_MODE_DEFAULT_CHOICES: tuple[str, ...] = (STAGE_MODE_ASK, *EXECUTION_MODES)


def default_stage_mode(setting_value: str | None) -> str:
    if setting_value in VALID_EXECUTION_MODES:
        return str(setting_value)
    return ""
