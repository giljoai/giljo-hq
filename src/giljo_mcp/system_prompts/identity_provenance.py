# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import datetime

from giljo_mcp.system_prompts.service import MODE_ADDITIONS, SCOPE_PRODUCT


_PREFIX = "identity source:"


def format_identity_source(
    scope: str,
    *,
    updated_at: datetime | None = None,
    product_name: str | None = None,
    mode: str | None = None,
) -> str:
    if mode == MODE_ADDITIONS and scope == SCOPE_PRODUCT:
        whose = f"your product additions for {product_name}" if product_name else "your product additions"
        saved = f" (saved {updated_at.strftime('%Y-%m-%d')})" if updated_at is not None else ""
        return f"{_PREFIX} built-in + {whose}{saved}"
    if scope == SCOPE_PRODUCT:
        named = f" ({product_name})" if product_name else ""
        return f"{_PREFIX} product override{named}{_saved_clause(updated_at)}"
    return f"{_PREFIX} built-in default"


def append_identity_source(identity_text: str, source_line: str) -> str:
    return f"{identity_text}\n\n{source_line}"


def _saved_clause(updated_at: datetime | None) -> str:
    if updated_at is None:
        return ""
    return f", saved {updated_at.strftime('%Y-%m-%d')}"
