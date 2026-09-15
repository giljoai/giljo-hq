# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

from giljo_mcp.exceptions import ValidationError


_IDENTITY_STRIP_RE = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\ufeff]")


def sanitize_agent_identity(raw: str) -> str:
    return _IDENTITY_STRIP_RE.sub("", raw).strip()


def validate_from_agent(raw: str | None, *, max_len: int = 64) -> str | None:
    if raw is not None and not isinstance(raw, str):
        raise ValidationError(
            "from_agent must be a string.",
            context={"operation": "comm_thread.post", "from_agent_type": type(raw).__name__},
        )
    raw = raw or ""
    if len(raw) > max_len:
        raise ValidationError(
            f"from_agent must be <= {max_len} chars.",
            context={"operation": "comm_thread.post", "from_agent_len": len(raw)},
        )
    cleaned = sanitize_agent_identity(raw)
    if raw and not cleaned:
        raise ValidationError(
            "from_agent contained no usable characters after sanitization.",
            context={"operation": "comm_thread.post"},
        )
    return cleaned or None


_DISPLAY_NAME_ALLOWED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")


def validate_agent_display_name(raw: str | None, *, max_len: int = 128) -> str:
    if raw is not None and not isinstance(raw, str):
        raise ValidationError(
            "agent_display_name must be a string.",
            context={"operation": "agent_spawn", "agent_display_name_type": type(raw).__name__},
        )
    name = (raw or "").strip()
    if not name:
        raise ValidationError(
            "agent_display_name cannot be empty.",
            context={"operation": "agent_spawn"},
        )
    if len(name) > max_len:
        raise ValidationError(
            f"agent_display_name must be <= {max_len} chars.",
            context={"operation": "agent_spawn", "agent_display_name_len": len(name)},
        )
    if not _DISPLAY_NAME_ALLOWED_RE.match(name):
        raise ValidationError(
            "agent_display_name may only contain letters, digits, spaces, hyphens, "
            "and underscores -- no parentheses or other punctuation.",
            context={"operation": "agent_spawn", "agent_display_name": name},
        )
    return name
