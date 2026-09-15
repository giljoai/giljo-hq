# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re


MAX_SLUG_LENGTH = 48

FALLBACK_SLUG = "product"

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify_product_name(name: str | None) -> str:
    slug = _NON_SLUG_CHARS.sub("-", (name or "").strip().lower()).strip("-")
    if not slug:
        return FALLBACK_SLUG
    return slug[:MAX_SLUG_LENGTH].strip("-") or FALLBACK_SLUG


__all__ = ["FALLBACK_SLUG", "MAX_SLUG_LENGTH", "slugify_product_name"]
