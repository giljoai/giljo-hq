# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging


logger = logging.getLogger(__name__)

_PLACEHOLDER_CALL = "thread_id=<your coordination thread>"
_PHASE1_ANCHOR = '   - "I will actively coordinate. Wake me when agents need attention or on status changes."'


def apply_thread_reference(protocol: str, comm_thread_id: str | None) -> str:
    if not protocol or not comm_thread_id:
        return protocol
    if _PLACEHOLDER_CALL not in protocol:
        logger.warning(
            "coordination-thread placeholder not found in the orchestrator protocol; "
            "the render drifted. Leaving it unchanged."
        )
        return protocol
    protocol = protocol.replace(_PLACEHOLDER_CALL, f'thread_id="{comm_thread_id}"')
    note = (
        f"   - Your coordination thread is `{comm_thread_id}` — the server enrolled you on "
        "it while serving this mission, so a post directed at you reaches you. Use that id "
        "for every `get_thread_history` / `post_to_thread` call below.\n"
    )
    return protocol.replace(_PHASE1_ANCHOR, note + _PHASE1_ANCHOR, 1)
