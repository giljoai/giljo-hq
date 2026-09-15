# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from giljo_mcp.models.auth import LoginLockout
from giljo_mcp.utils.log_sanitizer import sanitize


if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 10
LOCKOUT_WINDOW = timedelta(minutes=15)


class AccountLockedError(Exception):

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(f"Account temporarily locked; retry after {self.retry_after_seconds}s")


@dataclass(frozen=True)
class LockoutOutcome:

    failed_count: int
    locked_until: datetime | None
    just_locked: bool


def _normalize(identifier: str) -> str:
    return identifier.strip().lower()


class LoginLockoutService:

    async def assert_not_locked(self, session: AsyncSession, identifier: str, ip: str) -> None:
        ident = _normalize(identifier)
        result = await session.execute(
            select(LoginLockout.locked_until).where(
                LoginLockout.identifier == ident,
                LoginLockout.ip_address == ip,
            )
        )
        row = result.first()
        if row is None or row[0] is None:
            return
        locked_until = row[0]
        now = datetime.now(UTC)
        if locked_until > now:
            raise AccountLockedError(int((locked_until - now).total_seconds()))

    async def record_failure(self, session: AsyncSession, identifier: str, ip: str) -> LockoutOutcome:
        ident = _normalize(identifier)
        now = datetime.now(UTC)

        await session.execute(
            pg_insert(LoginLockout)
            .values(
                id=str(uuid4()),
                identifier=ident,
                ip_address=ip,
                failed_count=0,
                first_failed_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["identifier", "ip_address"])
        )

        result = await session.execute(
            select(LoginLockout)
            .where(LoginLockout.identifier == ident, LoginLockout.ip_address == ip)
            .with_for_update()
        )
        row = result.scalar_one()

        if row.locked_until is not None and row.locked_until <= now:
            count = 1
            row.locked_until = None
        else:
            count = row.failed_count + 1

        just_locked = False
        if row.locked_until is None and count >= MAX_FAILED_ATTEMPTS:
            row.locked_until = now + LOCKOUT_WINDOW
            just_locked = True

        row.failed_count = count
        row.updated_at = now
        await session.flush()

        if just_locked:
            logger.warning(
                "login lockout triggered identifier=%s ip=%s until=%s",
                sanitize(ident),
                sanitize(ip),
                row.locked_until,
            )
        return LockoutOutcome(failed_count=count, locked_until=row.locked_until, just_locked=just_locked)

    async def clear(self, session: AsyncSession, identifier: str, ip: str) -> None:
        ident = _normalize(identifier)
        await session.execute(
            delete(LoginLockout).where(
                LoginLockout.identifier == ident,
                LoginLockout.ip_address == ip,
            )
        )

    async def clear_for_identifiers(self, session: AsyncSession, identifiers: Iterable[str]) -> None:
        idents = sorted({_normalize(i) for i in identifiers if i and i.strip()})
        if not idents:
            return
        await session.execute(delete(LoginLockout).where(LoginLockout.identifier.in_(idents)))
