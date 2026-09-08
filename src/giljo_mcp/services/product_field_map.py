# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Single source of truth for translating product context fields into
``ProductService.update_product()`` kwargs.

Two independent writers target the SAME product fields across the ``products`` row
and its three 1:1 relation tables (``tech_stack`` / ``architecture`` / ``test_config``):

* the vision-extraction writer (``tools/vision_analysis.py``), keyed by extraction
  field names, and
* the context-tuning writer (``services/product_tuning_service.py``), keyed by
  tuning section keys.

Both used to maintain parallel block-grouping mappers (BE-6225d removed the
hand-maintained cross-reference warning that flagged the duplication). They now share
the canonical column->block registry and the grouping logic here: each writer
translates its own input vocabulary into a flat ``{column: value}`` mapping, then calls
:func:`assemble_update_kwargs` to group it into ``update_product`` kwargs.

``ProductRepository.update_config_relations`` merges relation blocks per-field, so a
partial block dict only touches the columns it carries -- callers do not need to
re-supply the full block.
"""

from typing import Any


# Direct columns on the ``products`` row (each must also be in
# ProductService._ALLOWED_PRODUCT_FIELDS to actually persist).
PRODUCT_DIRECT_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "core_features",
    "brand_guidelines",
    "target_platforms",
    "project_path",
    "extraction_custom_instructions",
)

# Columns living on the three 1:1 relation tables, grouped by the ``update_product``
# block name (matches ProductRepository.update_config_relations).
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
    """Return the ``update_product`` block a canonical column belongs to.

    ``"tech_stack"`` / ``"architecture"`` / ``"test_config"`` for a relation column,
    ``"products"`` for a direct product column, or ``None`` if the column is unknown.
    """
    for block, columns in RELATION_BLOCK_FIELDS.items():
        if column in columns:
            return block
    if column in PRODUCT_DIRECT_FIELDS:
        return "products"
    return None


def assemble_update_kwargs(column_values: dict[str, Any]) -> dict[str, Any]:
    """Group a flat ``{column: value}`` mapping into ``update_product`` kwargs.

    Direct product columns stay top-level; relation columns are grouped into their
    block's dict (partial -- ``update_config_relations`` merges per-field, so columns
    not present in a block are left untouched). Unknown columns are dropped.
    """
    kwargs: dict[str, Any] = {}
    for column, value in column_values.items():
        block = block_for_column(column)
        if block in RELATION_BLOCK_FIELDS:
            kwargs.setdefault(block, {})[column] = value
        elif block == "products":
            kwargs[column] = value
    return kwargs
