# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from giljo_mcp.models.system_setting import SystemSetting
from giljo_mcp.services.settings_service import SystemSettingsService


pytestmark = pytest.mark.asyncio

_PREFIX = "inf0061_test."


@pytest.fixture
async def settings(db_session):
    await db_session.execute(delete(SystemSetting).where(SystemSetting.key.startswith(_PREFIX, autoescape=True)))
    return SystemSettingsService(db_session)


async def _value(db_session, key: str) -> str | None:
    return (await db_session.execute(select(SystemSetting.value).where(SystemSetting.key == key))).scalar_one_or_none()


async def test_a_marker_is_claimed_once_per_value_and_only_moves_forward(settings, db_session):
    key = f"{_PREFIX}month"
    assert await settings.advance_marker(key, "2026-10") is True
    assert await settings.advance_marker(key, "2026-10") is False, "a second worker must not claim the same month"
    assert await settings.advance_marker(key, "2026-09") is False, "a stale clock must not move the marker back"
    assert await _value(db_session, key) == "2026-10"
    assert await settings.advance_marker(key, "2026-11") is True
    assert await _value(db_session, key) == "2026-11"


async def test_counters_add_and_sum_by_prefix(settings, db_session):
    await settings.add_to_counter(f"{_PREFIX}n.2026-10-01", 2)
    await settings.add_to_counter(f"{_PREFIX}n.2026-10-01", 3)
    await settings.add_to_counter(f"{_PREFIX}n.2026-10-31", 4)
    await settings.add_to_counter(f"{_PREFIX}n.2026-11-01", 50)
    assert await _value(db_session, f"{_PREFIX}n.2026-10-01") == "5"
    assert await settings.sum_counters(f"{_PREFIX}n.2026-10-") == 9
    assert await settings.sum_counters(f"{_PREFIX}n.2026-12-") == 0


async def test_the_prefix_is_literal_not_a_like_pattern(settings):
    await settings.add_to_counter(f"{_PREFIX}aXb", 7)
    assert await settings.sum_counters(f"{_PREFIX}a_b") == 0
    assert await settings.sum_counters(f"{_PREFIX}%") == 0


async def test_old_counters_are_pruned_below_a_bound(settings):
    for day in ("2026-08-31", "2026-09-15", "2026-10-01"):
        await settings.add_to_counter(f"{_PREFIX}n.{day}", 1)
    await settings.delete_keys_before(f"{_PREFIX}n.", f"{_PREFIX}n.2026-09-")
    assert await settings.sum_counters(f"{_PREFIX}n.") == 2
