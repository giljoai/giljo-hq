# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Agent-identity token hardening (BE-9037, FE-9490).

A self-declared agent id (``from_agent``) feeds a FUNCTIONAL identity field on the
Agent Message Hub (recipient self-exclusion, baton/get_my_turn matching, read
cursors). A stray control or zero-width character silently forks that identity, so
strip them before the value reaches the DB. Slugs are preserved verbatim — the Hub
keys on the agent slug, not a UUID — so a legitimate id like ``BE-9037`` or
``CI2-orchestrator`` is unchanged.

FE-9490 adds a sibling boundary for ``agent_display_name`` (the human-facing badge
label, not the addressing slug above): a name carrying punctuation such as a
parenthetical suffix breaks initials derivation in the frontend badge UI (e.g.
``"Reviewer (Phase 5)"`` renders as ``"R("``). Reject it at spawn time instead of
letting it reach the DB. This is a NEW-write gate only — agents spawned before this
gate existed may already carry punctuation in their display name, and the frontend
badge helper tolerates that old shape on read rather than breaking their badges.

Edition Scope: CE.
"""

from __future__ import annotations

import re

from giljo_mcp.exceptions import ValidationError


# C0/C1 control chars + zero-width / BOM / line-separator codepoints.
_IDENTITY_STRIP_RE = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\ufeff]")


def sanitize_agent_identity(raw: str) -> str:
    """Strip control + zero-width chars, then surrounding whitespace, from an agent
    identity token. Returns ``''`` when nothing usable survives (the caller turns
    that into a clean 422 rather than writing a blank/garbage addressing key)."""
    return _IDENTITY_STRIP_RE.sub("", raw).strip()


def validate_from_agent(raw: str | None, *, max_len: int = 64) -> str | None:
    """Harden an agent-supplied ``from_agent`` at the write boundary (BE-9037):
    type-check, length-cap, and sanitize. Returns the clean slug, or ``None`` when
    omitted/blank (the user-post path). Raises :class:`ValidationError` (clean 422,
    never a 500) on a non-string, an over-long value, or a value that is only
    control/zero-width chars. The slug is preserved verbatim — the Hub keys on the
    agent slug, never a UUID — and an unknown-but-sane slug is accepted (ad-hoc lane
    ids are legitimate)."""
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


# Letters, digits, spaces, hyphens, and underscores -- the character set every
# existing agent template name / display name already uses (e.g. "orchestrator",
# "Backend-Implementer", the auto-suffixed "Reviewer-2"). Anything else, most
# commonly a parenthetical annotation, is refused rather than silently stripped:
# the caller chose the name and should be told, not have it mangled.
_DISPLAY_NAME_ALLOWED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")


def validate_agent_display_name(raw: str | None, *, max_len: int = 128) -> str:
    """Reject punctuation in a NEW agent display name at the write boundary
    (FE-9490). Raises :class:`ValidationError` (clean 422, never a 500) on a
    non-string, blank/whitespace-only, an over-long value, or a value containing
    a character outside letters/digits/spaces/hyphens/underscores. Returns the
    trimmed name on success.

    This only gates where a NEW display name is written (agent spawn / succession);
    it does not touch rows already in the DB, per the data-facing convention DoD --
    agents spawned before this validator existed may already carry a punctuated
    name, and those keep rendering (the frontend badge helper tolerates the old
    shape on read)."""
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
