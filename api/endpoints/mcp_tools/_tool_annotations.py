# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mcp.types import ToolAnnotations

from api.endpoints.mcp_tools._base import SCOPE_READ, TOOL_SCOPES


_READ_SCOPED_BUT_MUTATING: frozenset[str] = frozenset({"get_thread_history"})


def _tool_hints(name: str, *, destructive: bool = False, open_world: bool = False) -> ToolAnnotations:
    scope = TOOL_SCOPES[name]
    read_only = name not in _READ_SCOPED_BUT_MUTATING and scope == SCOPE_READ
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=None if read_only else destructive,
        open_world_hint=open_world,
    )


def sync_annotation_titles(tools: Iterable[Any]) -> None:
    for tool in tools:
        annotations = tool.annotations
        if annotations is None:
            raise ValueError(
                f"tool {tool.name!r} has no annotations block -- its wrapper must build one via _tool_hints()"
            )
        if not tool.title:
            raise ValueError(f"tool {tool.name!r} has no title -- pass title= to its @mcp.tool decorator")
        if annotations.title:
            continue
        tool.annotations = annotations.model_copy(update={"title": tool.title})
