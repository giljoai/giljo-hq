# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6208b repo-layer regression — list_threads must not 500 on a UUID query.

Bug: list_threads extracted all digits from the query and cast to int for a
serial-equality match. A 36-char UUID yields a huge integer that overflows the
serial column's 32-bit cast -> Postgres 500. Fix: only take the serial branch
when the digit string is a plausible serial length (<= 9 digits).

A CHT-#### / short numeric query must STILL resolve by serial.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be6208b_{suffix}"


async def test_search_threads_full_uuid_does_not_500(db_session):
    tenant = _tk("uuid")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        await repo.create_thread(db_session, tenant, subject="design discussion")

        # A full UUID query: digit-rich, far longer than any serial. Must return
        # a normal (empty) result, never raise a DB overflow 500.
        results = await repo.search_threads(db_session, tenant, str(uuid4()))
    assert results == []


async def test_search_threads_short_serial_still_resolves(db_session):
    tenant = _tk("serial")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        thread = await repo.create_thread(db_session, tenant, subject="first thread")
        assert thread.serial == 1

        by_alias = await repo.search_threads(db_session, tenant, "CHT-0001")
        by_number = await repo.search_threads(db_session, tenant, "1")

    assert any(t.id == thread.id for t in by_alias)
    assert any(t.id == thread.id for t in by_number)
