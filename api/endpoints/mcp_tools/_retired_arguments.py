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


@dataclass(frozen=True)
class RetiredArgument:

    argument: str
    replacements: Mapping[Any, str]
    accepted: frozenset[Any] = field(default_factory=frozenset)


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
}


def retired_argument_rejection(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    for spec in RETIRED_ARGUMENTS.get(tool_name, ()):
        if spec.argument not in arguments:
            continue
        value = arguments[spec.argument]
        hashable = isinstance(value, Hashable)
        if hashable and value in spec.accepted:
            continue
        replacement = spec.replacements.get(value) if hashable else None
        if replacement is not None:
            message = (
                f"{tool_name} no longer takes {spec.argument}={value!r}. "
                f"Call {replacement} instead. Nothing was changed."
            )
        else:
            names = ", ".join(dict.fromkeys(spec.replacements.values()))
            message = (
                f"{tool_name} no longer takes a {spec.argument} argument. "
                f"The operations it used to select are now separate tools: {names}. Nothing was changed."
            )
        return validation_rejection(field=spec.argument, constraint=CONSTRAINT_RETIRED_ARGUMENT, message=message)
    return None
