# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

from giljo_mcp.exceptions import ValidationError


HANDOVER_TYPE_ABBR = "HND"

REQUIRED_HANDOVER_HEADINGS: tuple[str, ...] = (
    "## Verify before trusting",
    "## Waiting on the operator",
    "## Cannot testify",
)

HANDOVER_SHAPE_FIELD = "description"
HANDOVER_SHAPE_CONSTRAINT = "handover_headings"
HANDOVER_CONTENT_CONSTRAINT = "handover_heading_content"

_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}\s")


def missing_handover_headings(description: str | None) -> list[str]:
    text = description or ""
    return [heading for heading in REQUIRED_HANDOVER_HEADINGS if heading not in text]


def handover_shape_message(missing: list[str]) -> str:
    named = ", ".join(f"'{heading}'" for heading in missing)
    return (
        f"A handover task (task_type='{HANDOVER_TYPE_ABBR}') must carry these headings in its "
        f"description, and is missing {named}. Required: "
        f"{', '.join(repr(h) for h in REQUIRED_HANDOVER_HEADINGS)}. "
        "They exist so the next person can check your claims instead of trusting them: put "
        "each claim next to the command that verifies it, say what needs the operator, and "
        "say plainly what you did not verify."
    )


def _section_is_answered(text: str, heading: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        at = stripped.find(heading)
        if at == -1:
            continue
        if stripped[at + len(heading) :].strip(" \t:-"):
            return True
        for following in lines[index + 1 :]:
            if not following.strip():
                continue
            if _HEADING_LINE.match(following):
                break
            return True
    return False


def empty_handover_headings(description: str | None) -> list[str]:
    text = description or ""
    return [
        heading for heading in REQUIRED_HANDOVER_HEADINGS if heading in text and not _section_is_answered(text, heading)
    ]


def handover_content_message(empty: list[str]) -> str:
    named = ", ".join(f"'{heading}'" for heading in empty)
    return (
        f"A handover task (task_type='{HANDOVER_TYPE_ABBR}') carries {named} with nothing "
        "written under it, so it was not stored. A heading on its own is not a section: "
        "the successor cannot tell an empty one from a section its author meant to leave "
        "out. Write at least one line under each -- 'nothing' is a real answer and is "
        "accepted, because a stated nothing is a claim you can be held to."
    )


def handover_shape_error(description: str | None, *, operation: str) -> ValidationError | None:
    missing = missing_handover_headings(description)
    if missing:
        return ValidationError(
            message=handover_shape_message(missing),
            context={
                "operation": operation,
                "field": HANDOVER_SHAPE_FIELD,
                "constraint": HANDOVER_SHAPE_CONSTRAINT,
                "missing_headings": missing,
            },
        )

    empty = empty_handover_headings(description)
    if empty:
        return ValidationError(
            message=handover_content_message(empty),
            context={
                "operation": operation,
                "field": HANDOVER_SHAPE_FIELD,
                "constraint": HANDOVER_CONTENT_CONSTRAINT,
                "empty_headings": empty,
            },
        )

    return None


def require_handover_shape(description: str | None, *, operation: str) -> None:
    error = handover_shape_error(description, operation=operation)
    if error is not None:
        raise error
