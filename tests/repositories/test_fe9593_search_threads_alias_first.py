# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.comm import CommThread
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_fe9593_{suffix}"


async def _quote(repo: CommThreadRepository, session, tenant: str, thread: CommThread, text: str) -> None:
    await repo.persist_thread_message(
        session,
        tenant_key=tenant,
        thread_id=thread.id,
        project_id=None,
        content=text,
        from_agent_id="lane-a",
        from_display_name="LANE_A",
        message_type="broadcast",
        priority="normal",
        requires_action=False,
        recipient_ids=[],
    )


async def test_exact_serial_hit_ranks_first_over_newer_threads_that_quote_it(db_session):
    tenant = _tk("rank")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        target = await repo.create_thread(db_session, tenant, subject="the one we want")
        assert target.serial == 1
        quoter_a = await repo.create_thread(db_session, tenant, subject="unrelated a")
        quoter_b = await repo.create_thread(db_session, tenant, subject="unrelated b")
        await _quote(repo, db_session, tenant, quoter_a, "see CHT-0001 for the decision")
        await _quote(repo, db_session, tenant, quoter_b, "CHT-0001 has the log")
        await db_session.flush()

        results = await repo.search_threads(db_session, tenant, "CHT-0001")

    ids = [t.id for t in results]
    assert ids[0] == target.id, ids
    assert set(ids[1:]) == {quoter_a.id, quoter_b.id}


async def test_alias_and_bare_number_both_rank_the_exact_thread_first(db_session):
    tenant = _tk("forms")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        target = await repo.create_thread(db_session, tenant, subject="first")
        newer = await repo.create_thread(db_session, tenant, subject="newer")
        await _quote(repo, db_session, tenant, newer, "about 1 and CHT-0001")
        await db_session.flush()

        for query in ("CHT-0001", "cht-0001", "1"):
            results = await repo.search_threads(db_session, tenant, query)
            assert results and results[0].id == target.id, (query, [t.subject for t in results])


async def test_five_digit_serial_renders_in_full_and_is_searchable(db_session):
    tenant = _tk("wide")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        seed = await repo.create_thread(db_session, tenant, subject="seed")
        seed.serial = 9999
        await db_session.flush()
        wide = await repo.create_thread(db_session, tenant, subject="past the edge")
        assert wide.serial == 10000
        assert wide.taxonomy_alias == "CHT-10000"

        by_alias = await repo.search_threads(db_session, tenant, "CHT-10000")
        by_number = await repo.search_threads(db_session, tenant, "10000")

    assert by_alias and by_alias[0].id == wide.id
    assert by_number and by_number[0].id == wide.id
