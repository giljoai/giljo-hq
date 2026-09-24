# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def record_tool_call(tenant_key: str, method_name: str) -> None:
    from api.app_state import state as app_state

    app_state.mcp_call_count[tenant_key] = app_state.mcp_call_count.get(tenant_key, 0) + 1
    tool_day_key = (tenant_key, method_name, datetime.now(UTC).date())
    app_state.mcp_tool_call_count[tool_day_key] = app_state.mcp_tool_call_count.get(tool_day_key, 0) + 1


def record_untenanted_tool_call(ctx: Any, method_name: str) -> None:
    from api.endpoints.mcp_tools import _base

    try:
        tenant_key = _base._resolve_tenant(ctx)
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return
    record_tool_call(tenant_key, method_name)
