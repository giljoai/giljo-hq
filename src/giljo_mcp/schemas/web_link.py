# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from urllib.parse import urlsplit


def web_link_or_blank(value: str | None) -> str | None:
    if value is None or not value.strip():
        return value
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("must be an http:// or https:// link")
    return value
