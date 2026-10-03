# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.startup.migration_check import check_pending_migrations, get_pending_migration_info


def _unreachable_state():
    return SimpleNamespace(db_manager=SimpleNamespace(database_url="postgresql://nobody:x@127.0.0.1:1/nowhere"))


@pytest.mark.asyncio
async def test_check_pending_migrations_answers_unknown_when_the_database_cannot_be_reached():
    assert await check_pending_migrations(_unreachable_state()) is None


def test_pending_migration_info_marks_an_unknown_check():
    assert get_pending_migration_info(_unreachable_state()) == {"unknown": True}


@pytest.mark.asyncio
async def test_banner_emitter_leaves_the_banner_alone_when_the_check_is_unknown():
    from api.startup.background_tasks import _emit_pending_migrations_banner

    service = SimpleNamespace(resolve_by_dedupe_key=AsyncMock(), upsert_by_dedupe_key=AsyncMock())
    await _emit_pending_migrations_banner(service, "tk", {"unknown": True})
    service.resolve_by_dedupe_key.assert_not_awaited()
    service.upsert_by_dedupe_key.assert_not_awaited()
