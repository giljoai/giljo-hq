# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""LoginLockoutService — per-(identifier, IP) password-login lockout.

SEC-3001a Wave 2 item 6. Owns the ``login_lockouts`` table (the owning service
for that entity). Pre-auth and system-level: a failed login happens before any
tenant context exists, so every method takes a caller-controlled ``AsyncSession``
and the table carries no ``tenant_key`` (the tenant guard skips it — see
``models/auth.py::LoginLockout``).

Design (SEC-3001a Wave 2 item 6):
- Lock the **(identifier, IP)** pair, not the user row — so an attacker spamming
  a victim's email from another IP can never lock the victim out of their own
  (email, IP) pair (no lockout-as-DoS).
- ``MAX_FAILED_ATTEMPTS`` failures → a ``LOCKOUT_WINDOW`` lock that AUTO-unlocks
  when the window passes; a successful login or password reset clears it.

Concurrency: ``record_failure`` does an ``INSERT ... ON CONFLICT DO NOTHING`` to
materialise the row race-free, then ``SELECT ... FOR UPDATE`` to serialise the
read-modify-write for that key. The per-IP login rate limiter (5/min) already
throttles bursts in front of this, so contention on a single key is low.
"""

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

# Design decision: 10 failed attempts from one (identifier, IP) pair → a 15-min
# lockout that auto-unlocks. Module constants (not env flags) — the values are a
# deliberate product decision, not a deployment knob.
MAX_FAILED_ATTEMPTS = 10
LOCKOUT_WINDOW = timedelta(minutes=15)


class AccountLockedError(Exception):
    """Raised when a login is attempted against a currently-locked (identifier, IP).

    Carries ``retry_after_seconds`` so the endpoint can emit a ``Retry-After``
    header on the 429. This is a deliberate domain rejection, not an internal
    error — the endpoint translates it to an HTTP 429.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(f"Account temporarily locked; retry after {self.retry_after_seconds}s")


@dataclass(frozen=True)
class LockoutOutcome:
    """Result of recording one failed attempt."""

    failed_count: int
    locked_until: datetime | None
    just_locked: bool  # True only on the attempt that crossed the threshold


def _normalize(identifier: str) -> str:
    """Lowercase + strip the submitted identifier for stable keying."""
    return identifier.strip().lower()


class LoginLockoutService:
    """Service for the per-(identifier, IP) login lockout. Session-in pattern."""

    async def assert_not_locked(self, session: AsyncSession, identifier: str, ip: str) -> None:
        """Raise ``AccountLockedError`` iff ``(identifier, ip)`` is locked right now.

        Read-only gate, called BEFORE the password verify. A lock whose window
        has already passed reads as not-locked (auto-unlock); ``record_failure``
        resets its counter on the next failure.
        """
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
        """Record one failed password attempt for ``(identifier, ip)``.

        Returns the new state; ``just_locked`` is True only on the attempt that
        crosses ``MAX_FAILED_ATTEMPTS`` (the caller fires the lockout notice then).
        """
        ident = _normalize(identifier)
        now = datetime.now(UTC)

        # Materialise the row race-free; a concurrent first-failure no-ops here.
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

        # Serialise the read-modify-write for this key.
        result = await session.execute(
            select(LoginLockout)
            .where(LoginLockout.identifier == ident, LoginLockout.ip_address == ip)
            .with_for_update()
        )
        row = result.scalar_one()

        # An expired lock window resets the counter (auto-unlock on next activity).
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
        """Drop the ``(identifier, ip)`` counter — called on a successful login."""
        ident = _normalize(identifier)
        await session.execute(
            delete(LoginLockout).where(
                LoginLockout.identifier == ident,
                LoginLockout.ip_address == ip,
            )
        )

    async def clear_for_identifiers(self, session: AsyncSession, identifiers: Iterable[str]) -> None:
        """Drop EVERY (identifier, *) row for the given identifiers — instant unlock.

        Called after a successful password reset, with both the user's username
        and email, so a reset releases the account from every IP at once.
        """
        idents = sorted({_normalize(i) for i in identifiers if i and i.strip()})
        if not idents:
            return
        await session.execute(delete(LoginLockout).where(LoginLockout.identifier.in_(idents)))
