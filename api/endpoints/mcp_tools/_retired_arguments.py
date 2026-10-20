# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Any

from api.endpoints.mcp_tools._base import validation_rejection


CONSTRAINT_RETIRED_ARGUMENT = "retired_argument"

ANY_VALUE = object()


@dataclass(frozen=True)
class RetiredArgument:

    argument: str
    replacements: Mapping[Any, str]
    accepted: frozenset[Any] = field(default_factory=frozenset)
    accept_falsy: bool = False


RETIRED_ARGUMENTS: dict[str, tuple[RetiredArgument, ...]] = {
    "stage_project": (
        RetiredArgument(
            argument="action",
            replacements={
                "unstage": "unstage_project",
                "restage": "unstage_project",
                "cancel_staging": "update_project with status='cancelled'",
            },
            accepted=frozenset({"stage"}),
        ),
    ),
    "update_task": (
        RetiredArgument(
            argument="convert_to_project",
            replacements={True: "promote_task_to_project"},
            accepted=frozenset({False}),
        ),
    ),
    "save_roadmap": (
        RetiredArgument(argument="remove", replacements={ANY_VALUE: "remove_roadmap_items"}, accept_falsy=True),
    ),
    "post_to_thread": (
        RetiredArgument(
            argument="rename_to",
            replacements={ANY_VALUE: "update_thread with subject=<the new name>"},
            accept_falsy=True,
        ),
    ),
}


def retired_argument_rejection(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    for spec in RETIRED_ARGUMENTS.get(tool_name, ()):
        if spec.argument not in arguments:
            continue
        value = arguments[spec.argument]
        if spec.accept_falsy and not value:
            continue
        hashable = isinstance(value, Hashable)
        if hashable and value in spec.accepted:
            continue
        replacement = spec.replacements.get(value) if hashable else None
        if replacement is not None:
            message = (
                f"{tool_name} no longer takes {spec.argument}={value!r}. "
                f"Call {replacement} instead. Nothing was changed."
            )
        elif ANY_VALUE in spec.replacements:
            message = (
                f"{tool_name} no longer takes a {spec.argument} argument. "
                f"Call {spec.replacements[ANY_VALUE]} instead. Nothing was changed."
            )
        else:
            names = ", ".join(dict.fromkeys(spec.replacements.values()))
            message = (
                f"{tool_name} no longer takes a {spec.argument} argument. "
                f"The operations it used to select are now separate tools: {names}. Nothing was changed."
            )
        return validation_rejection(field=spec.argument, constraint=CONSTRAINT_RETIRED_ARGUMENT, message=message)
    return None
