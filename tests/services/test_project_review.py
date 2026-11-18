# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

import pytest

from giljo_mcp.services.project_helpers import broadcast_deferred_events
from giljo_mcp.services.project_review import stamp_review
from tests.services.test_ba1_start_list_walk_facts import _finished, _Wire
from tests.services.test_fe0072a_start_list_service import _Account


pytestmark = pytest.mark.asyncio


async def test_stamp_review_stamps_once_and_parks_one_event(db_session, db_manager):
    account = _Account(db_session, db_manager)
    wire = _Wire()
    project = await _finished(account, datetime(2026, 11, 17, tzinfo=UTC))

    first = await stamp_review(db_session, wire, account.tenant_key, project.id)
    again = await stamp_review(db_session, wire, account.tenant_key, project.id)
    await broadcast_deferred_events(db_session)

    assert (first, again) == (True, False)
    [(tenant_key, event_type, data)] = wire.sent
    assert (tenant_key, event_type) == (account.tenant_key, "project_update")
    assert (data["project_id"], data["update_type"], data["status"]) == (project.id, "reviewed", "completed")


async def test_stamp_review_never_touches_another_tenants_project(db_session, db_manager):
    mine = _Account(db_session, db_manager)
    project = await _finished(mine, datetime(2026, 11, 17, tzinfo=UTC))
    other = _Account(db_session, db_manager)
    wire = _Wire()

    stamped = await stamp_review(db_session, wire, other.tenant_key, project.id)

    assert stamped is False
    assert wire.sent == []
