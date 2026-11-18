# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from giljo_mcp.exceptions import ValidationError


PRODUCT_DIRECT_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "core_features",
    "brand_guidelines",
    "target_platforms",
    "project_path",
    "extraction_custom_instructions",
)

RELATION_BLOCK_FIELDS: dict[str, tuple[str, ...]] = {
    "tech_stack": (
        "programming_languages",
        "frontend_frameworks",
        "backend_frameworks",
        "databases_storage",
        "infrastructure",
        "dev_tools",
    ),
    "architecture": (
        "primary_pattern",
        "design_patterns",
        "api_style",
        "architecture_notes",
        "coding_conventions",
    ),
    "test_config": (
        "quality_standards",
        "test_strategy",
        "coverage_target",
        "testing_frameworks",
    ),
}


def block_for_column(column: str) -> str | None:
    for block, columns in RELATION_BLOCK_FIELDS.items():
        if column in columns:
            return block
    if column in PRODUCT_DIRECT_FIELDS:
        return "products"
    return None


def assemble_update_kwargs(column_values: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for column, value in column_values.items():
        block = block_for_column(column)
        if block in RELATION_BLOCK_FIELDS:
            kwargs.setdefault(block, {})[column] = value
        elif block == "products":
            kwargs[column] = value
    return kwargs


PRODUCT_TEXT_MAX_LENGTH = 20_000
_CAPPED_TEXT_FIELDS = ("description", "core_features", "brand_guidelines", "extraction_custom_instructions")
_COLUMN_MAX_LENGTH = {"test_config.test_strategy": 50}


def validate_text_lengths(fields: dict[str, Any], *, current: Any, context: dict[str, Any]) -> None:
    candidates = [(name, fields.get(name), getattr(current, name, None)) for name in _CAPPED_TEXT_FIELDS]
    for block in RELATION_BLOCK_FIELDS:
        incoming = fields.get(block)
        if isinstance(incoming, dict):
            stored = getattr(current, block, None)
            candidates += [(f"{block}.{key}", value, getattr(stored, key, None)) for key, value in incoming.items()]
    for label, value, stored in candidates:
        limit = _COLUMN_MAX_LENGTH.get(label, PRODUCT_TEXT_MAX_LENGTH)
        if isinstance(value, str) and len(value) > limit and value != stored:
            raise ValidationError(message=f"{label}: Must be at most {limit} characters.", context=context)
