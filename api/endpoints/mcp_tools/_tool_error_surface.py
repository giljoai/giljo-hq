# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

from mcp.server.mcpserver.exceptions import MCPServerError, ToolError
from mcp.shared.exceptions import MCPError

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._announcement_hook import first_reply_hook_installed, first_reply_meta
from api.endpoints.mcp_tools._base import _CLEAN_VALIDATION_ERRORS, _SQL_LEAK_SIGNATURE
from giljo_mcp.exceptions import BaseGiljoError


logger = logging.getLogger(__name__)

_WRAPPED_MARKER = "__giljo_tool_error_surface__"

_PYDANTIC_INPUT_ECHO = re.compile(r",\s*input_value=.*?(?=,\s*input_type=)", re.DOTALL)


def redact_input_echo(message: str) -> str:
    return _PYDANTIC_INPUT_ECHO.sub("", message)


def is_anticipated_rejection(exc: BaseException) -> bool:
    if isinstance(exc, ToolError | MCPError):
        return False
    if isinstance(exc, MCPServerError):
        return True
    if isinstance(exc, BaseGiljoError):
        return exc.default_status_code < 500
    if isinstance(exc, _CLEAN_VALIDATION_ERRORS):
        return not _SQL_LEAK_SIGNATURE.search(str(exc))
    return False


async def _first_reply_additions(ctx: Any) -> dict[str, Any]:
    if ctx is None or not first_reply_hook_installed():
        return {}
    try:
        tenant_key = _base._resolve_tenant(ctx)
    except (AttributeError, RuntimeError):
        return {}
    return await first_reply_meta(ctx, tenant_key, _base._resolve_user_id)


def _with_notices(message: str, additions: dict[str, Any]) -> str:
    parts = [message]
    if hint := additions.get("setup_hint"):
        parts.append(hint)
    if notice := additions.get("announcement"):
        parts.append(f"{notice['title']}. {notice['summary']} {notice['action']}")
    return " ".join(parts)


def _surface_rejections(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            if is_anticipated_rejection(exc):
                logger.info("MCP tool rejection: %s", exc)
                text = exc.agent_facing_str() if isinstance(exc, BaseGiljoError) else str(exc)
                additions = await _first_reply_additions(kwargs.get("ctx"))
                raise ToolError(_with_notices(redact_input_echo(text), additions)) from exc
            raise
        if isinstance(result, dict) and (additions := await _first_reply_additions(kwargs.get("ctx"))):
            result = {**result, "_meta": {**(result.get("_meta") or {}), **additions}}
        return result

    setattr(wrapper, _WRAPPED_MARKER, True)
    return wrapper


def preserve_tool_rejections(tools: Iterable[Any]) -> None:
    for tool in tools:
        if getattr(tool.fn, _WRAPPED_MARKER, False):
            continue
        if not tool.is_async:
            raise RuntimeError(f"preserve_tool_rejections: tool {tool.name!r} is sync; only async tools are wrapped")
        tool.fn = _surface_rejections(tool.fn)
