# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from api.endpoints.mcp_tools._base import blank_text_rejection, validation_rejection
from giljo_mcp.services.text_field_validation import has_line_break_or_control


CONSTRAINT_SINGLE_LINE = "single_line"


def name_text_rejection(value: str, field: str, *, entity: str) -> dict[str, Any] | None:
    if not value.strip():
        return blank_text_rejection(field, entity=entity)
    if has_line_break_or_control(value):
        return validation_rejection(
            field=field,
            constraint=CONSTRAINT_SINGLE_LINE,
            message=f"{entity} {field} must be a single line: line breaks and other control characters are not allowed.",
        )
    return None
