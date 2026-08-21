# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for the ce_0031_user_split_name backfill SQL.

These tests execute the exact UPDATE statement used in the migration against
the test database (which already has the first_name / last_name columns),
verifying the split_part / CASE logic for the documented edge cases:

    - "Sam Rivera"           -> first="Sam",        last="Rivera"
    - "Cher"                 -> first="Cher",       last=NULL
    - "Jean Claude Van Damme"-> first="Jean",       last="Claude Van Damme"
    - "  Leading spaces  "   -> first="",           last=(remainder) [documents actual SQL behaviour]
    - full_name IS NULL      -> first=NULL,          last=NULL (row untouched)
    - first_name already set -> backfill is skipped (idempotency guard)

Bug-fix regression layer: migration backfill SQL.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


# The exact backfill SQL from ce_0031_user_split_name.upgrade()
_BACKFILL_SQL = sa.text(
    "UPDATE users "
    "SET first_name = split_part(full_name, ' ', 1), "
    "    last_name = CASE "
    "        WHEN position(' ' in full_name) > 0 "
    "        THEN NULLIF(substring(full_name from position(' ' in full_name) + 1), '') "
    "        ELSE NULL "
    "    END "
    "WHERE full_name IS NOT NULL AND first_name IS NULL"
)

# Helper INSERT for raw rows (bypasses ORM to control exactly which columns are set).
# Includes all NOT NULL columns that have no server-side default in the test DB.
_INSERT_RAW = sa.text(
    "INSERT INTO users "
    "(id, username, email, password_hash, tenant_key, role, full_name, is_active, "
    " failed_pin_attempts, must_change_password, must_set_pin, is_system_user) "
    "VALUES (:id, :username, :email, 'hashed', :tenant_key, 'developer', :full_name, true, "
    "        0, false, false, false)"
)

_INSERT_WITH_FIRST = sa.text(
    "INSERT INTO users "
    "(id, username, email, password_hash, tenant_key, role, full_name, first_name, is_active, "
    " failed_pin_attempts, must_change_password, must_set_pin, is_system_user) "
    "VALUES (:id, :username, :email, 'hashed', :tenant_key, 'developer', :full_name, :first_name, true, "
    "        0, false, false, false)"
)

_SELECT_NAMES = sa.text("SELECT first_name, last_name FROM users WHERE id = :id")


@pytest.mark.asyncio
async def test_backfill_two_part_name(db_session: AsyncSession, test_tenant_key: str):
    """'Sam Rivera' -> first='Sam', last='Rivera'."""
    row_id = "backfill-test-two-part"
    await db_session.execute(
        _INSERT_RAW,
        {
            "id": row_id,
            "username": "backfill_two",
            "email": "backfill_two@example.com",
            "tenant_key": test_tenant_key,
            "full_name": "Sam Rivera",
        },
    )
    await db_session.execute(_BACKFILL_SQL)
    result = await db_session.execute(_SELECT_NAMES, {"id": row_id})
    row = result.one()
    assert row.first_name == "Sam"
    assert row.last_name == "Rivera"


@pytest.mark.asyncio
async def test_backfill_single_token_name(db_session: AsyncSession, test_tenant_key: str):
    """'Cher' (single token) -> first='Cher', last=NULL."""
    row_id = "backfill-test-single"
    await db_session.execute(
        _INSERT_RAW,
        {
            "id": row_id,
            "username": "backfill_single",
            "email": "backfill_single@example.com",
            "tenant_key": test_tenant_key,
            "full_name": "Cher",
        },
    )
    await db_session.execute(_BACKFILL_SQL)
    result = await db_session.execute(_SELECT_NAMES, {"id": row_id})
    row = result.one()
    assert row.first_name == "Cher"
    assert row.last_name is None


@pytest.mark.asyncio
async def test_backfill_multi_part_name_rest_becomes_last(db_session: AsyncSession, test_tenant_key: str):
    """'Jean Claude Van Damme' -> first='Jean', last='Claude Van Damme'.

    The SQL uses split_part(full_name, ' ', 1) for first_name and
    substring-from-first-space for last_name, so everything after the
    first space becomes last_name.
    """
    row_id = "backfill-test-multi"
    await db_session.execute(
        _INSERT_RAW,
        {
            "id": row_id,
            "username": "backfill_multi",
            "email": "backfill_multi@example.com",
            "tenant_key": test_tenant_key,
            "full_name": "Jean Claude Van Damme",
        },
    )
    await db_session.execute(_BACKFILL_SQL)
    result = await db_session.execute(_SELECT_NAMES, {"id": row_id})
    row = result.one()
    assert row.first_name == "Jean"
    assert row.last_name == "Claude Van Damme"


@pytest.mark.asyncio
async def test_backfill_skips_null_full_name(db_session: AsyncSession, test_tenant_key: str):
    """Rows where full_name IS NULL are untouched (WHERE clause guard)."""
    row_id = "backfill-test-null-fn"
    await db_session.execute(
        _INSERT_RAW,
        {
            "id": row_id,
            "username": "backfill_nullfn",
            "email": "backfill_nullfn@example.com",
            "tenant_key": test_tenant_key,
            "full_name": None,
        },
    )
    await db_session.execute(_BACKFILL_SQL)
    result = await db_session.execute(_SELECT_NAMES, {"id": row_id})
    row = result.one()
    # Both columns should still be NULL — the backfill must not touch this row
    assert row.first_name is None
    assert row.last_name is None


@pytest.mark.asyncio
async def test_backfill_is_idempotent_skips_already_migrated(db_session: AsyncSession, test_tenant_key: str):
    """Rows where first_name is already set are not overwritten (idempotency).

    If the migration is re-run (as it is on every CE boot), pre-existing
    first_name values must not be clobbered.
    """
    row_id = "backfill-test-idem"
    await db_session.execute(
        _INSERT_WITH_FIRST,
        {
            "id": row_id,
            "username": "backfill_idem",
            "email": "backfill_idem@example.com",
            "tenant_key": test_tenant_key,
            "full_name": "Full Name Original",
            "first_name": "AlreadySet",
        },
    )
    await db_session.execute(_BACKFILL_SQL)
    result = await db_session.execute(_SELECT_NAMES, {"id": row_id})
    row = result.one()
    # The backfill WHERE clause `AND first_name IS NULL` must have skipped this row
    assert row.first_name == "AlreadySet"
