# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Response-size bounds for agent-facing MCP list tools (BE-9468).

Facts about the **MCP wire**, not about any one domain: how long a payload really is
once serialized, and how to drop whole rows until a response fits a character budget.

**Why this lives at the ``services/`` level rather than inside one service.** It was
written first for ``task_service`` because tasks needed it first, and ``list_projects``
needs the identical rule. Importing it across sibling domain services would have made
``task_service`` a runtime dependency of ``project_service`` -- via a private module,
for a helper that has nothing to do with tasks -- where the two packages import nothing
from each other today. **A shared home costs one module; the alternative costs a
coupling and a second copy that agree only until they do not.** Precedent for this
placement: ``_error_helpers``, ``_session_helpers``, ``_idem_crypto``,
``_predecessor_context``.

``task_service._mcp_read_layer`` re-exports these under its own names so its shipped
call sites and tests keep working verbatim.

Edition Scope: Both.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic_core import to_json

from giljo_mcp.exceptions import ValidationError


# The response-size backstop. A ROW cap cannot bound a response whose rows are
# arbitrarily large -- measured, a single project row at ``mode='planning'`` with a
# 9,000-char description is ~1,976 tokens, more than twice an entire ten-row index
# response. So a row bound and a size bound are not alternatives; the row bound is the
# fan-out guard and this is the context-window guard.
#
# **48,000 chars. The number has moved TWICE, each time onto firmer ground, and the
# history is kept here because a later reader who only sees the current value will
# re-derive one of the two superseded, weaker justifications.**
#
# MOVE 1 (80,000 -> 60,000): 80,000 was a context-window budget -- ~26,000-31,000 tokens
# at the measured wire ratio of 2.6-3.1 chars/token, 13-15% of a 200k window. Correct
# arithmetic, wrong ruler: the limit that actually binds is the MCP client's
# per-tool-result cap, far smaller than a context window and reached first. Measured on a
# live 471-project board (2026-08-19): a 75,986-char response sat UNDER the 80,000
# ceiling, reported ``truncated: false`` -- and the client refused to deliver it at all
# ("exceeds maximum allowed tokens"). 75,986 chars against ~25,000 tokens implies ~3.04
# chars/token, inside the measured band, which is what identified the client cap as
# ~25,000 TOKENS rather than any character count -- still an ESTIMATE, inferred from one
# client's error string.
#
# MOVE 2 (60,000 -> 48,000, BLACK-BOX QA, 2026-08-19): the same client cap, this time
# MEASURED rather than inferred. Bisection against the live client narrowed the refusal
# threshold to a 465-char bracket: **refusal begins somewhere in (49,595, 50,060]**. At
# 60,000 chars, a response sized 49,596-50,060 would report ``truncated: false`` and the
# client would still refuse it whole -- the identical silent-incompleteness failure MOVE 1
# existed to remove, reopened by a value that had cleared only the estimate, not the
# measured floor. 48,000 sits below the bracket's floor with margin at every measured
# chars/token ratio in the 2.6-3.1 band.
#
# **Cost, paid knowingly:** an agent now sees roughly 180 projects or 115 tasks per call
# (down from ~230/150 at 60,000; ~300/200 at the original 80,000), and a walk that
# crossed a 471-row board in 5 pages now takes 6. The truncation signal already reports
# every cut honestly, so no caller can silently break -- it just pages one more time.
MCP_LIST_CHAR_CEILING = 48_000

# Headroom for keys the transport adds AFTER a service returns -- today ``_meta``
# (~37 chars). Reserving it is what makes the ceiling a real postcondition rather than
# an approximate one: the in-repo ``tools/context_tools/_response_ceiling`` helper writes
# its own truncation metadata after its last size check and overshoots its ceiling by
# exactly 64 chars as a result. **A bound that does not hold is worse than no bound,
# because it reports success.**
TRANSPORT_ENVELOPE_ALLOWANCE = 256


def wire_length(payload: Any) -> int:
    """Serialized length as the MCP wire actually produces it.

    ``pydantic_core.to_json`` emits COMPACT JSON and is the real serializer
    (``fastmcp/tools/base.py``). Measuring with ``json.dumps`` defaults counts separator
    whitespace that never goes over the wire, which inflates the number and lets a size
    check pass on bytes that do not exist.
    """
    return len(to_json(payload, fallback=str).decode())


def fit_rows_to_char_ceiling(
    rows: list[dict[str, Any]],
    *,
    envelope: dict[str, Any],
    ceiling: int = MCP_LIST_CHAR_CEILING,
) -> tuple[list[dict[str, Any]], int]:
    """Drop whole ROWS from the tail until the response fits. Never trims fields.

    Returns ``(kept_rows, dropped_count)``.

    **Rows, not fields, and the distinction is the whole design.** The in-repo field
    trimmer strips attributes off every row until the total fits, which on a list
    produces husks: its protected-field set covers the display label and not the
    identifier, so the caller is handed rows it can read and cannot act on. A list tool
    needs FEWER rows, not thinner ones -- a half-row is not a usable answer. Every row
    that survives here is complete.

    The tail is what goes. **That is only "the least-wanted rows" because the caller
    ordered them that way** -- this function makes no ordering claim of its own, and a
    caller whose truncation message says which rows were dropped owns keeping that
    message true.

    ``envelope`` is the response dict WITHOUT its rows. It is charged against the budget
    up front, together with a fixed allowance for keys the transport appends later, so
    the returned response genuinely lands under ``ceiling`` rather than approximately
    under it. The envelope passed in must already include the truncation block that a
    cut will add -- the caller builds it that way on purpose, because measuring the
    budget before adding metadata and then adding metadata is exactly how a ceiling
    silently stops holding.
    """
    budget = ceiling - wire_length(envelope) - TRANSPORT_ENVELOPE_ALLOWANCE
    if budget <= 0:
        return [], len(rows)

    kept: list[dict[str, Any]] = []
    used = 0
    for row in rows:
        # +1 for the comma that joins this row to the previous one in the array.
        cost = wire_length(row) + 1
        if used + cost > budget:
            break
        used += cost
        kept.append(row)

    return kept, len(rows) - len(kept)


# --------------------------------------------------------------------------
# The continuation cursor (BE-9469 item 2)
# --------------------------------------------------------------------------
#
# ONE encode/decode, imported by every list tool that pages. Two copies of a cursor
# codec agree until they do not, and the failure mode is a token minted by one tool and
# rejected -- or worse, silently misread -- by another.
#
# **Prior art, copied rather than invented:** Stripe's list idiom (``limit`` + opaque
# continuation token + ``has_more``) and the MCP spec's own ``nextCursor``. In-repo,
# ``get_thread_history`` already ships ``after_message_id``/``since``/``tail`` and agents
# follow it in practice. The shape below is those, with the position carried inside the
# token instead of asked for as a separate parameter.
#
# **STATELESS.** The server stores nothing and expires nothing. Everything except the
# position is re-derived from the request on every call, so there is no cursor table to
# grow, no TTL to tune, and no stored state that can fall out of step with the data.
#
# **WHY THE TOKEN IS SAFE TO HAND AN AGENT, stated because "opaque" is not a security
# argument.** It is base64, not a signature -- anyone can read it and anyone can forge
# one. That is acceptable because of what it is USED for: the decoded values become
# operands in a WHERE comparison and nothing else. The row is never fetched by its id, no
# field of it is echoed back, and every query still filters ``tenant_key`` server-side. So
# a forged token buys a POSITION in the caller's own tenant-scoped ordering -- it cannot
# read another tenant's row, and it cannot report whether an id exists anywhere, because
# the response is identical either way. The token deliberately carries NO tenant key: a
# value that must never be trusted is better absent than present-and-ignored.


CURSOR_VERSION = 1

# Base64url, and the padding is stripped on the way out and restored on the way in.
# ``=`` survives a JSON round trip but not every URL or shell an operator will paste a
# token into, and a token that breaks in transport reads to an agent as a server bug.
_CURSOR_ENCODING = "utf-8"


class CursorRejectedError(ValidationError):
    """A cursor that cannot be honoured. Carries the MCP-boundary rejection code.

    A ``ValidationError`` subclass so an unexpected path yields a 4xx rather than a 500 --
    but the MCP tool wrapper catches THIS type specifically and returns the BE-6081 Tier-2
    structured rejection instead. The distinction is the point: a refused cursor is
    something the agent can fix by restarting the walk, so it should arrive as normal tool
    content carrying a remedy, not as ``isError``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, context={"operation": "list_cursor", "error": code})
        self.code = code


def filter_fingerprint(filters: dict[str, Any]) -> str:
    """A short, stable hash of the filter set a cursor was issued under.

    **INCLUDED: everything that changes WHICH rows are in the ordering.** Change any of it
    mid-walk and the position the token records names a different row, so the remaining
    pages skip or repeat with nothing in the response saying so.

    **EXCLUDED, deliberately: ``limit``, ``depth`` and ``mode``.** They change how many
    rows a page holds and how fat each row is -- not which rows exist, nor in what order.
    An agent that walks in ``mode='triage'`` and switches to a richer mode for one page is
    doing something reasonable and gets a correct, complete walk. Refusing that would be a
    page-size bound wearing a correctness check's clothes.

    Sorted keys and dropped ``None``s are what make the hash stable: two calls meaning the
    same filter set must fingerprint identically regardless of keyword order, and a filter
    left explicitly unset must not differ from one absent from the dict.
    """
    material = {key: value for key, value in sorted(filters.items()) if value is not None}
    return hashlib.sha256(to_json(material, fallback=str)).hexdigest()[:16]


def encode_cursor(*, axis: str, sort_value: Any, row_id: str, fingerprint: str) -> str:
    """Mint the opaque continuation token for the LAST row of a page.

    ``sort_value`` may be ``None``. On an axis with a NULLS-FIRST region that is a real
    position rather than a missing value, and the keyset comparison cannot be built without
    knowing which region the cursor stands in.

    Datetimes are written as ISO-8601 with their offset so the value survives the round
    trip exactly. A truncated timestamp is a position that lands between two rows and
    quietly drops or duplicates whichever one it lands on.
    """
    payload = {
        "v": CURSOR_VERSION,
        "a": axis,
        "s": sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value,
        "i": row_id,
        "f": fingerprint,
    }
    return base64.urlsafe_b64encode(to_json(payload, fallback=str)).decode(_CURSOR_ENCODING).rstrip("=")


def worst_case_cursor_charge(axis: str, fingerprint: str) -> str:
    """A token guaranteed AT LEAST as long as any real token for this axis and fingerprint.

    **Why a placeholder rather than the real token.** The token has to be charged against
    the size budget BEFORE the row cut, because it is part of the response that must fit --
    but it can only be MINTED after the cut, because it must name the last row actually
    delivered. Minting it early and reusing it is the bug: if the size backstop drops rows,
    an early token points past rows the caller never received, which is a silent skip.

    So the budget is charged this upper bound, and the real token replaces it afterwards.
    The ceiling still holds because the replacement can only be shorter or equal: every
    field is fixed-width except the position value, and a NULL position is shorter than the
    full ISO timestamp used here. A 36-character all-``f`` id is the widest a UUID gets.
    """
    return encode_cursor(
        axis=axis,
        sort_value="9999-12-31T23:59:59.999999+00:00",
        row_id="f" * 36,
        fingerprint=fingerprint,
    )


def decode_cursor(token: str, *, axis: str, fingerprint: str, allow_null_sort_value: bool = False) -> tuple[Any, str]:
    """Validate a token against THIS request and return ``(sort_value, row_id)``.

    Every rejection is a :class:`CursorRejectedError` naming a remedy, because the caller is an
    agent that has to do something next -- and a cursor is the one parameter it can neither
    inspect nor repair, so "invalid cursor" without an instruction leaves it with no move.

    **A token whose filters or axis do not match this request is REFUSED, never honoured.**
    The tempting alternative -- ignore the mismatch and page anyway -- returns rows that
    are neither the requested filter's rows nor a complete walk of anything, and reports
    success. That is the exact defect class this read layer exists to remove, so a refusal
    carrying a remedy is strictly better than a plausible answer.

    The axis is checked separately from the fingerprint even though the axis is DERIVED
    from the filters. It costs one comparison, and it means a future change to how the axis
    is selected cannot silently make a stale token look valid.

    ``allow_null_sort_value`` defaults to **False**, refusing a missing/null ``s`` the same
    way a non-timestamp ``s`` is refused (BE-9469 QA follow-up, U50-F1). A caller passes
    ``True`` only for an axis with a real NULL region -- this module has no notion of which
    axis that is, on purpose (it is a fact about the WIRE, not about any one domain's keyset),
    so the caller decides. Without this, a cursor whose ``s`` key is absent decodes to a
    ``None`` sort value that looks identical to a legitimately-minted NULL-region position, and
    an axis with no NULL region has no way to express "no position" -- it raises deep in the
    keyset builder instead, past every catch this boundary has for a REFUSED cursor.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode(_CURSOR_ENCODING)))
    except Exception as exc:  # every malformed token gets the same remedy
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
