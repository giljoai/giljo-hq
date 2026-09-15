# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any


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
