# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta


RECOVER_WINDOW_DAYS = 30


def recover_window_expired(deleted_at: datetime | None, *, now: datetime | None = None) -> bool:
    if deleted_at is None:
        return False
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=UTC)
    return deleted_at < recover_window_cutoff(now=now)


def recover_window_cutoff(*, now: datetime | None = None) -> datetime:
    reference = now or datetime.now(UTC)
    return reference - timedelta(days=RECOVER_WINDOW_DAYS)
