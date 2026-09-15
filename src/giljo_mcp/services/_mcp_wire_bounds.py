# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic_core import to_json

from giljo_mcp.exceptions import ValidationError


MCP_LIST_CHAR_CEILING = 48_000

TRANSPORT_ENVELOPE_ALLOWANCE = 256


def wire_length(payload: Any) -> int:
    return len(to_json(payload, fallback=str).decode())


def fit_rows_to_char_ceiling(
    rows: list[dict[str, Any]],
    *,
    envelope: dict[str, Any],
    ceiling: int = MCP_LIST_CHAR_CEILING,
) -> tuple[list[dict[str, Any]], int]:
    budget = ceiling - wire_length(envelope) - TRANSPORT_ENVELOPE_ALLOWANCE
    if budget <= 0:
        return [], len(rows)

    kept: list[dict[str, Any]] = []
    used = 0
    for row in rows:
        cost = wire_length(row) + 1
        if used + cost > budget:
            break
        used += cost
        kept.append(row)

    return kept, len(rows) - len(kept)




CURSOR_VERSION = 1

_CURSOR_ENCODING = "utf-8"


class CursorRejectedError(ValidationError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, context={"operation": "list_cursor", "error": code})
        self.code = code


def filter_fingerprint(filters: dict[str, Any]) -> str:
    material = {key: value for key, value in sorted(filters.items()) if value is not None}
    return hashlib.sha256(to_json(material, fallback=str)).hexdigest()[:16]


def encode_cursor(*, axis: str, sort_value: Any, row_id: str, fingerprint: str) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "a": axis,
        "s": sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value,
        "i": row_id,
        "f": fingerprint,
    }
    return base64.urlsafe_b64encode(to_json(payload, fallback=str)).decode(_CURSOR_ENCODING).rstrip("=")


def worst_case_cursor_charge(axis: str, fingerprint: str) -> str:
    return encode_cursor(
        axis=axis,
        sort_value="9999-12-31T23:59:59.999999+00:00",
        row_id="f" * 36,
        fingerprint=fingerprint,
    )


def decode_cursor(token: str, *, axis: str, fingerprint: str, allow_null_sort_value: bool = False) -> tuple[Any, str]:
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode(_CURSOR_ENCODING)))
    except Exception as exc:
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor is not a token this server issued. Call again without cursor to "
            "restart the walk from the first page.",
        ) from exc

    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise CursorRejectedError(
            "CURSOR_VERSION_UNSUPPORTED",
            f"cursor was issued by a different version of this server (expected v{CURSOR_VERSION}). "
            "Call again without cursor to restart the walk from the first page.",
        )
    row_id = payload.get("i")
    if not isinstance(row_id, str) or not row_id:
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor does not name the row it points at. Call again without cursor to "
            "restart the walk from the first page.",
        )
    if payload.get("a") != axis:
        raise CursorRejectedError(
            "CURSOR_AXIS_MISMATCH",
            "cursor was issued against a different sort order than this request uses -- the "
            "filters that select the ordering have changed. Call again without cursor to "
            "restart the walk under the current filters.",
        )
    if payload.get("f") != fingerprint:
        raise CursorRejectedError(
            "CURSOR_FILTER_MISMATCH",
            "cursor was issued under a different filter set than this request uses, so "
            "continuing from it would skip or repeat rows. Call again without cursor to "
            "restart the walk under the current filters, or reissue the original filters to "
            "keep using this cursor.",
        )

    raw_sort = payload.get("s")
    if raw_sort is None:
        if allow_null_sort_value:
            return None, row_id
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor's position value is missing. Call again without cursor to restart the walk from the first page.",
        )
    if not isinstance(raw_sort, str):
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor's position value is not readable. Call again without cursor to restart "
            "the walk from the first page.",
        )
    try:
        return datetime.fromisoformat(raw_sort), row_id
    except ValueError as exc:
        raise CursorRejectedError(
            "CURSOR_MALFORMED",
            "cursor's position value is not a timestamp this server issued. Call again "
            "without cursor to restart the walk from the first page.",
        ) from exc
