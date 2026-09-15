# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any

from giljo_mcp.tools.context_tools._response_ceiling import _apply_response_ceiling


def assemble_fetch_context_response(
    *,
    categories: list[str],
    all_data: dict[str, Any],
    all_directives: dict[str, Any],
    all_errors: list[dict[str, str]],
    categories_returned: list[str],
    categories_empty: list[str],
    all_category_metadata: dict[str, Any],
    effective_depths: dict[str, Any],
    output_format: str,
    last_modified: dict[str, str],
) -> dict[str, Any]:
    depth_applied = {c: effective_depths.get(c) for c in categories}

    if output_format == "structured":
        response_data = all_data
    else:
        response_data = {}
        for cat_data in all_data.values():
            if isinstance(cat_data, dict):
                response_data.update(cat_data)
            else:
                response_data[str(type(cat_data))] = cat_data

    response: dict[str, Any] = {
        "source": "fetch_context",
        "categories_requested": list(categories),
        "categories_returned": categories_returned,
        "categories_empty": categories_empty,
        "data": response_data,
        "last_modified": last_modified,
        "metadata": {
            "format": output_format,
            "depth_config_applied": depth_applied,
            "categories": all_category_metadata,
        },
    }

    if all_directives:
        response["directive"] = all_directives

    if all_errors:
        response["errors"] = all_errors

    return _apply_response_ceiling(response)
