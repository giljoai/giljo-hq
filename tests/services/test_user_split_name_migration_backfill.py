# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


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
    assert row.first_name is None
    assert row.last_name is None


@pytest.mark.asyncio
async def test_backfill_is_idempotent_skips_already_migrated(db_session: AsyncSession, test_tenant_key: str):
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
    assert row.first_name == "AlreadySet"
