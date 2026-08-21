# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""What a Hub post's parameters must satisfy before anything is written (BE-9475).

``post_to_thread`` accepts two fields whose legal values are a fixed set rather than a
shape: ``set_status`` (the thread's lifecycle) and ``my_status`` (the poster's own claim
about what it is doing). Neither can be expressed as a length cap or a type, so both need
a membership check, and both must run BEFORE anything is persisted.

WHY THIS IS IN THE OWNING SERVICE'S PATH AND NOT ONLY AT THE MCP BOUNDARY. The boundary
wrapper checks ``my_status`` itself, because that is where an AI caller gets a structured,
self-correcting refusal naming the valid set. But the REST endpoint and every internal
caller reach ``CommThreadService.post_to_thread`` without passing through that wrapper at
all, and an unchecked value would then surface as a 500 from a column cap instead of a
clean rejection. This is the backstop beneath the boundary, not a duplicate of it — the
house rule is that the owning service validates its own input.

``resolve_loop_interval`` (FE-6140) lives here for the same reason: it is the third
member of one family -- bounds and membership checks on the post's own parameters, every
one of which must run before the session opens, none of which needs the repository, the
thread row, or the author. That shared shape is what makes them a module rather than a
pile.

Extracted rather than inlined for the same reason the BE-9289a (``comm_author_identity``)
and BE-9292a (``comm_baton_targets``) seams were: it keeps ``comm_thread_service`` under
the 800-line CI guardrail, and the caller stays inside the 200-line function cap -- which
on this file is not slack to spend. ``post_to_thread`` sat at 197 of 200 on master before
this project, and a concurrent change from another session took it to 199, so two
independently-green branches merged cleanly to 201 and would have turned master red.

Edition Scope: CE.
"""

from __future__ import annotations

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import VALID_SELF_REPORTED_STATUSES


# Loose status set the tool surface accepts on a status-setting post. The column itself
# tolerates freeform labels (BE-6054a), but the tool boundary constrains agent input to
# the known lifecycle to keep the board legible.
SETTABLE_THREAD_STATUSES = ("open", "active", "resolved", "closed")

# FE-6140: bounds for the auto-check-in interval (minutes) carried on a loop_directive
# post. 1 min floor, 24h ceiling -- a wider net than the FE slider (5..60), but a hard
# sanity bound for the MCP path so the column never receives unbounded agent input.
LOOP_INTERVAL_MIN_MINUTES = 1
LOOP_INTERVAL_MAX_MINUTES = 1440


def validate_post_vocabularies(set_status: str | None, self_reported_status: str | None) -> None:
    """Raise ``ValidationError`` for an out-of-vocabulary post field; return None if fine.

    ``None`` means "not supplied" and is always acceptable for both fields — omitting
    ``set_status`` leaves the thread's status untouched, and omitting ``my_status`` leaves
    any previous declaration in place. Only a value that is PRESENT and unrecognised is
    refused, so neither check can turn an ordinary post into an error.
    """
    if set_status is not None and set_status not in SETTABLE_THREAD_STATUSES:
        raise ValidationError(
            f"set_status must be one of {SETTABLE_THREAD_STATUSES}, got '{set_status}'.",
            context={"operation": "comm_thread.post", "set_status": set_status},
        )
    if self_reported_status is not None and self_reported_status not in VALID_SELF_REPORTED_STATUSES:
        raise ValidationError(
            f"my_status must be one of {VALID_SELF_REPORTED_STATUSES}, got '{self_reported_status}'.",
            context={"operation": "comm_thread.post", "self_reported_status": self_reported_status},
        )


def resolve_loop_interval(loop_directive: bool, loop_interval_minutes: int | None) -> int | None:
    """The auto-check-in cadence to PERSIST for this post, or None (FE-6140).

    Returns None for anything that should not carry a cadence, so the caller stores the
    result rather than re-deciding: a non-directive post's stray interval is DROPPED
    rather than persisted, because a cadence on a message nobody loops on is a number
    that can only mislead whoever reads the row later.

    A supplied interval on a directive post is bounds-checked here rather than at the
    column, which takes freeform integers. The floor and ceiling are deliberately wider
    than the frontend slider (5..60): this is the sanity bound for the MCP path, not a UI
    constraint, and the two should not be confused.

    ``bool`` is excluded explicitly because it is a subclass of ``int`` in Python, so
    ``isinstance(True, int)`` is True and ``loop_interval_minutes=True`` would otherwise
    sail through as the integer 1 -- a silently-accepted nonsense cadence.
    """
    if not (loop_directive and loop_interval_minutes is not None):
        return None
    if not isinstance(loop_interval_minutes, int) or isinstance(loop_interval_minutes, bool):
        raise ValidationError(
            "loop_interval_minutes must be an integer number of minutes.",
            context={"operation": "comm_thread.post"},
        )
    if not (LOOP_INTERVAL_MIN_MINUTES <= loop_interval_minutes <= LOOP_INTERVAL_MAX_MINUTES):
        raise ValidationError(
            f"loop_interval_minutes must be between {LOOP_INTERVAL_MIN_MINUTES} and {LOOP_INTERVAL_MAX_MINUTES}.",
            context={"operation": "comm_thread.post", "loop_interval_minutes": loop_interval_minutes},
        )
    return loop_interval_minutes
