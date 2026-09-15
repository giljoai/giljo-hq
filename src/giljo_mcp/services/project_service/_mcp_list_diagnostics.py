# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import logging
from typing import Any


def log_payload_size_breakdown(
    logger: logging.Logger,
    projects_out: list[dict[str, Any]],
    depth: int,
    mode: str | None,
) -> None:
    try:
        total_bytes = len(json.dumps(projects_out, default=str))
        per_row: list[dict[str, Any]] = []
        for row in projects_out:
            field_sizes: dict[str, int] = {}
            for k, v in row.items():
                field_sizes[k] = len(json.dumps(v, default=str))
            top_field = max(field_sizes, key=field_sizes.get) if field_sizes else None
            per_row.append(
                {
                    "project_id": row.get("project_id"),
                    "taxonomy_alias": row.get("taxonomy_alias"),
                    "row_bytes": sum(field_sizes.values()),
                    "top_field": top_field,
                    "top_field_bytes": field_sizes.get(top_field, 0) if top_field else 0,
                }
            )
        logger.debug(
            "list_projects payload size: total_bytes=%d rows=%d depth=%d mode=%s breakdown=%s",
            total_bytes,
            len(projects_out),
            depth,
            mode,
            per_row,
        )
    except (TypeError, ValueError) as exc:
        logger.warning("list_projects payload-size instrumentation failed: %s", exc)
