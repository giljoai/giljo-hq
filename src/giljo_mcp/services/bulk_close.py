# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any, Literal


BULK_CLOSE_MAX = 500
BULK_EVENT_IDS_MAX = 100

BulkCloseAction = Literal["archive", "unarchive", "delete"]

REASON_NOT_FOUND = "not found"
REASON_IN_CHAIN = "in an active chain (use Deactivate Chain first)"
REASON_PENDING_HANDOVER = "pending handover (nobody has read it yet)"
REASON_NOT_AUTHORIZED = "not allowed (only the creator or an admin can change this task)"


class BulkCloseOutcome:

    def __init__(self) -> None:
        self.done: list[str] = []
        self.skipped: list[dict[str, str]] = []
        self.failed: list[dict[str, str]] = []

    def skip(self, item_id: str, reason: str) -> None:
        self.skipped.append({"id": item_id, "reason": reason})

    def fail(self, item_id: str, reason: str) -> None:
        self.failed.append({"id": item_id, "reason": reason})

    def as_dict(self) -> dict[str, Any]:
        return {"done": self.done, "skipped": self.skipped, "failed": self.failed}


def unique_ids(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def bulk_event_data(action: str, done: list[str]) -> dict[str, Any]:
    return {
        "action": action,
        "count": len(done),
        "ids": done[:BULK_EVENT_IDS_MAX],
        "truncated": len(done) > BULK_EVENT_IDS_MAX,
    }
