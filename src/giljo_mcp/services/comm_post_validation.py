# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.comm import VALID_SELF_REPORTED_STATUSES


SETTABLE_THREAD_STATUSES = ("open", "active", "resolved", "closed")

LOOP_INTERVAL_MIN_MINUTES = 1
LOOP_INTERVAL_MAX_MINUTES = 1440


def validate_post_vocabularies(set_status: str | None, self_reported_status: str | None) -> None:
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
