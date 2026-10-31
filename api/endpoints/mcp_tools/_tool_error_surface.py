# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterable
from typing import Any

from mcp.server.mcpserver.exceptions import MCPServerError, ToolError
from mcp.shared.exceptions import MCPError

from api.endpoints.mcp_tools._base import _CLEAN_VALIDATION_ERRORS, _SQL_LEAK_SIGNATURE
from giljo_mcp.exceptions import BaseGiljoError


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


def _surface_rejections(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            if is_anticipated_rejection(exc):
                raise ToolError(redact_input_echo(str(exc))) from exc
            raise

    setattr(wrapper, _WRAPPED_MARKER, True)
    return wrapper


def preserve_tool_rejections(tools: Iterable[Any]) -> None:
    for tool in tools:
        if getattr(tool.fn, _WRAPPED_MARKER, False):
            continue
        if not tool.is_async:
            raise RuntimeError(f"preserve_tool_rejections: tool {tool.name!r} is sync; only async tools are wrapped")
        tool.fn = _surface_rejections(tool.fn)
