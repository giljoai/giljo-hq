# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import Any

from giljo_mcp.exceptions import ValidationError


_LINE_BREAK_OR_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def has_line_break_or_control(value: str) -> bool:
    return bool(_LINE_BREAK_OR_CONTROL.search(value))


def require_single_line(value: str, *, field: str, operation: str, entity: str, **context: Any) -> str:
    if has_line_break_or_control(value):
        raise ValidationError(
            message=f"{entity} {field} must be a single line: line breaks and other control characters are not allowed.",
            context={"operation": operation, "field": field, **context},
        )
    return value


def require_non_blank(
    value: Any,
    *,
    field: str,
    operation: str,
    entity: str,
    max_length: int | None = None,
    **context: Any,
) -> str:
    if value is None or not str(value).strip():
        raise ValidationError(
            message=f"{entity} {field} is required and cannot be empty or whitespace-only.",
            context={"operation": operation, "field": field, **context},
        )
    require_single_line(str(value), field=field, operation=operation, entity=entity, **context)
    if max_length is not None and len(value) > max_length:
        raise ValidationError(
            message=f"{entity} {field} exceeds {max_length} character limit (got {len(value)}).",
            context={"operation": operation, "field": field, **context},
        )
    return value
