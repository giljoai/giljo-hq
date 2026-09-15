# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError


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
    if max_length is not None and len(value) > max_length:
        raise ValidationError(
            message=f"{entity} {field} exceeds {max_length} character limit (got {len(value)}).",
            context={"operation": operation, "field": field, **context},
        )
    return value
