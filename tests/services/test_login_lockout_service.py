# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from giljo_mcp.models.auth import LoginLockout
from giljo_mcp.services.login_lockout_service import (
    MAX_FAILED_ATTEMPTS,
    AccountLockedError,
    LoginLockoutService,
)


_SVC = LoginLockoutService()
_IP_A = "203.0.113.10"
_IP_B = "203.0.113.20"


async def _fail_n(session, identifier: str, ip: str, n: int):
    outcome = None
    for _ in range(n):
        outcome = await _SVC.record_failure(session, identifier, ip)
    return outcome


@pytest.mark.asyncio
async def test_below_threshold_not_locked(db_session):
    ident = "below@example.com"
    outcome = await _fail_n(db_session, ident, _IP_A, MAX_FAILED_ATTEMPTS - 1)
    assert outcome.failed_count == MAX_FAILED_ATTEMPTS - 1
    assert outcome.just_locked is False
    await _SVC.assert_not_locked(db_session, ident, _IP_A)


@pytest.mark.asyncio
async def test_threshold_locks_and_blocks(db_session):
    ident = "lockme@example.com"
    outcome = await _fail_n(db_session, ident, _IP_A, MAX_FAILED_ATTEMPTS)
    assert outcome.just_locked is True
    assert outcome.locked_until is not None
    with pytest.raises(AccountLockedError):
        await _SVC.assert_not_locked(db_session, ident, _IP_A)


@pytest.mark.asyncio
async def test_different_ip_not_locked(db_session):
    ident = "victim@example.com"
    await _fail_n(db_session, ident, _IP_A, MAX_FAILED_ATTEMPTS)
    with pytest.raises(AccountLockedError):
        await _SVC.assert_not_locked(db_session, ident, _IP_A)
    await _SVC.assert_not_locked(db_session, ident, _IP_B)


@pytest.mark.asyncio
async def test_different_identifier_not_locked(db_session):
    await _fail_n(db_session, "a@example.com", _IP_A, MAX_FAILED_ATTEMPTS)
    await _SVC.assert_not_locked(db_session, "b@example.com", _IP_A)


@pytest.mark.asyncio
async def test_auto_unlock_after_window_resets_counter(db_session):
    ident = "expire@example.com"
    await _fail_n(db_session, ident, _IP_A, MAX_FAILED_ATTEMPTS)
    await db_session.execute(
        update(LoginLockout)
        .where(LoginLockout.identifier == ident, LoginLockout.ip_address == _IP_A)
        .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.flush()
    await _SVC.assert_not_locked(db_session, ident, _IP_A)
    outcome = await _SVC.record_failure(db_session, ident, _IP_A)
    assert outcome.failed_count == 1
    assert outcome.just_locked is False


@pytest.mark.asyncio
async def test_clear_removes_counter(db_session):
    ident = "success@example.com"
    await _fail_n(db_session, ident, _IP_A, 3)
    await _SVC.clear(db_session, ident, _IP_A)
    row = (
        await db_session.execute(
            select(LoginLockout).where(LoginLockout.identifier == ident, LoginLockout.ip_address == _IP_A)
        )
    ).scalar_one_or_none()
    assert row is None
    outcome = await _SVC.record_failure(db_session, ident, _IP_A)
    assert outcome.failed_count == 1


@pytest.mark.asyncio
async def test_clear_for_identifiers_unlocks_every_ip(db_session):
    username, email = "resetuser", "reset@example.com"
    await _fail_n(db_session, email, _IP_A, MAX_FAILED_ATTEMPTS)
    await _fail_n(db_session, email, _IP_B, MAX_FAILED_ATTEMPTS)
    with pytest.raises(AccountLockedError):
        await _SVC.assert_not_locked(db_session, email, _IP_A)

    await _SVC.clear_for_identifiers(db_session, [username, email])
    await _SVC.assert_not_locked(db_session, email, _IP_A)
    await _SVC.assert_not_locked(db_session, email, _IP_B)


@pytest.mark.asyncio
async def test_identifier_is_case_normalized(db_session):
    await _fail_n(db_session, "MixedCase@Example.com", _IP_A, MAX_FAILED_ATTEMPTS)
    with pytest.raises(AccountLockedError):
        await _SVC.assert_not_locked(db_session, "mixedcase@example.com", _IP_A)


@pytest.mark.asyncio
async def test_assert_not_locked_noop_when_no_row(db_session):
    await _SVC.assert_not_locked(db_session, "stranger@example.com", _IP_A)
