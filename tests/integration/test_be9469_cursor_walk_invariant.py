# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 item 2 -- THE WALK INVARIANT, at the real MCP transport.

**This is the acceptance test for the whole feature.** Everything else the cursor does is
plumbing; the only claim that matters to a caller is:

> walking a board with the cursor returns exactly ``counts.total`` rows, each exactly
> once, with no gaps.

If that holds, "list ALL my projects" is a loop instead of a workaround. If it does not,
the feature is worse than nothing, because it converts a visible truncation into an
invisible gap.

**Seeded so the walk cannot pass by luck.** The board carries, deliberately and together:

* a tie group -- several rows sharing one ``completed_at`` -- because ``now()`` is
  transaction-scoped in PostgreSQL and real boards are full of these;
* the NULLS-FIRST boundary, with unfinished work before finished work;
* page boundaries that fall INSIDE the tie group and INSIDE the null region, plus one that
  lands exactly ON the boundary, because those fail differently;
* a page size small enough that the walk takes several round trips.

Transport: the REAL ``@mcp.tool`` transport via ``create_connected_server_and_client_session``
-- the same boundary an agent in claude.ai reaches -- because a service-level test would not
prove the token survives serialization, nor that ``next_cursor`` is where a caller can find
it, nor that the parameter is on the tool schema at all.

Parallel-safe: each test generates a fresh ``tenant_key`` and purges its own rows in a
``finally`` block. These MCP-adapter calls commit for real, so there is no rollback
isolation to lean on. Edition Scope: Both.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio

# A page small enough that the walk takes several trips over a board of this size, so every
# hazard below lands on a boundary rather than inside one comfortable page.
PAGE = 3


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _content_text(call_tool_result) -> str:
    return "\n".join(t for t in (getattr(b, "text", None) for b in call_tool_result.content or []) if t)


@pytest_asyncio.fixture
async def mcp_client(db_manager, monkeypatch):
    """Wire a real ToolAccessor into the in-memory MCP transport.

    Copied from BE-9455's suite rather than shared: the fixture mutates process-wide
    ``app_state`` and restores it, and two suites reaching through one fixture object is
    how a restore gets skipped under xdist. Yields ``(client_factory, tenant_key)``.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def _day(day: int) -> datetime:
    return datetime(2026, 7, day, 12, 0, 0, tzinfo=UTC)


async def _seed_projects(db_manager, tenant_key: str, *, unfinished: int, finished: int, tie_size: int) -> list[str]:
    """Commit an active product plus a board built to break a careless cursor.

    ``unfinished`` rows have ``completed_at IS NULL`` (the NULLS-FIRST region);
    ``finished`` rows are completed, of which the first ``tie_size`` share ONE timestamp so
    the walk must cross a real tie group. Returns every seeded project id.

    The unfinished rows are ``inactive``, not ``active``: ``idx_project_single_active_per_product``
    is a partial unique index on ``status = 'active'``, so a product may hold only ONE active
    project. What this board needs is a NULL ``completed_at``, which ``inactive`` gives
    without fighting a real constraint.
    """
    product_id = str(uuid.uuid4())
    ids: list[str] = []
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9469 walk board {uuid.uuid4().hex[:6]}",
                description="BE-9469 -- the cursor walk invariant.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        for index in range(unfinished + finished):
            is_finished = index >= unfinished
            finished_index = index - unfinished
            project_id = str(uuid.uuid4())
            ids.append(project_id)
            session.add(
                Project(
                    id=project_id,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name=f"{'finished' if is_finished else 'unfinished'} {index:02d}",
                    description="Seeded for the cursor walk invariant.",
                    mission="Walk the whole board with no gaps and no repeats.",
                    status="completed" if is_finished else "inactive",
                    staging_status="staging_complete",
                    series_number=index + 1,
                    created_at=_day(1 + index),
                    completed_at=(_day(20) if finished_index < tie_size else _day(19 - finished_index))
                    if is_finished
                    else None,
                )
            )
        await session.commit()
    return ids


async def _seed_tasks(db_manager, tenant_key: str, *, count: int) -> list[str]:
    """Commit an active product plus ``count`` tasks written in ONE transaction.

    One transaction is the point, not a shortcut: ``created_at`` takes
    ``server_default=func.now()`` and PostgreSQL evaluates ``now()`` once per transaction,
    so every one of these rows carries a byte-identical timestamp. The whole board is a
    single tie group, and ``id`` alone has to carry the walk.
    """
    product_id = str(uuid.uuid4())
    ids: list[str] = []
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9469 task board {uuid.uuid4().hex[:6]}",
                description="BE-9469 -- the cursor walk invariant, task side.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        for index in range(count):
            task_id = str(uuid.uuid4())
            ids.append(task_id)
            session.add(
                Task(
                    id=task_id,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    title=f"tied task {index:02d}",
                    description="Seeded for the cursor walk invariant.",
                    status="pending",
                )
            )
        await session.commit()
    return ids


# The created_at window that separates the rows the post-fetch filter KEEPS from the rows it
# rejects. ``created_after`` runs in PYTHON after the SQL fetch, which is what makes a
# fully-rejected fetch window reachable at all.
#
# **It filters on a DIFFERENT column from the one the list is ORDERED by** (``completed_at``),
# and that independence is the whole trick: it lets rejected rows sit strictly BETWEEN two
# matching rows in completion order, which a filter on the ordering column could never do.
#
# ⚠ The first version of this fixture used ``taxonomy_alias_prefix`` and silently matched
# NOTHING. ``Project.taxonomy_alias`` is a SELECT-time ``column_property`` derived from type
# and serial, so a value assigned in the constructor is discarded -- the walk returned zero
# rows and looked like a cursor bug. Suspect the instrument first.
_KEEP_CREATED_AFTER = "2026-07-20T00:00:00+00:00"


async def _seed_filtered_run(db_manager, tenant_key: str) -> list[str]:
    """Seed two rows the filter KEEPS with a long run of rejected rows between them.

    Returns the ids the filter should keep. Position in the list is controlled through
    ``completed_at`` (the ordering column) and membership through ``created_at`` (the
    filtered column), so the six rejected rows sit strictly between the two matches however
    the uuids happen to sort.
    """
    product_id = str(uuid.uuid4())
    wanted: list[str] = []
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9469 filtered-run board {uuid.uuid4().hex[:6]}",
                description="BE-9469 -- a whole fetch window rejected by a post-fetch filter.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        # Completion order, newest first: one match, six rejects, one match.
        plan = [True] + [False] * 6 + [True]
        for index, is_wanted in enumerate(plan):
            project_id = str(uuid.uuid4())
            if is_wanted:
                wanted.append(project_id)
            session.add(
                Project(
                    id=project_id,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name=f"{'wanted' if is_wanted else 'rejected'} {index:02d}",
                    description="Seeded for the filtered-run walk.",
                    mission="Cross a fully rejected fetch window without stalling.",
                    status="completed",
                    staging_status="staging_complete",
                    series_number=index + 1,
                    # Inside the kept window vs far outside it.
                    created_at=_day(25) if is_wanted else datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
                    # Strictly descending, so the rejects sit between the two matches.
                    completed_at=_day(28 - index),
                )
            )
        await session.commit()
    return wanted


async def _call(client, tool: str, **kwargs):
    async with client() as mcp_session:
        return await mcp_session.call_tool(tool, kwargs)


async def _walk(
    client, tool: str, rows_key: str, id_key: str, *, max_pages: int = 40, **kwargs
) -> tuple[list[str], int]:
    """Walk a list tool to completion. Returns ``(ids seen in order, pages fetched)``.

    Written exactly as the tool's own description tells an agent to write it: call, read
    ``truncation.next_cursor``, pass it back with the SAME filters, stop when ``truncated``
    is false. Nothing here reaches past the response into the database -- if the documented
    loop does not terminate correctly, this test fails, which is the point.

    ``max_pages`` bounds a pathological repeat so a broken cursor surfaces as a wrong id
    list rather than as a hung test.
    """
    seen: list[str] = []
    cursor = ""
    for page_index in range(max_pages):
        result = await _call(client, tool, cursor=cursor, **kwargs)
        assert not result.is_error, f"page {page_index + 1} errored: {_content_text(result)!r}"
        payload = _payload(result)
        pages = page_index + 1
        seen.extend(row[id_key] for row in payload[rows_key])
        if not payload.get("truncated"):
            return seen, pages
        cursor = payload.get("truncation", {}).get("next_cursor", "")
        assert cursor, (
            f"page {pages} reported truncated=true but carried no next_cursor, so the walk "
            f"cannot continue. truncation block: {payload.get('truncation')!r}"
        )
    raise AssertionError(f"the walk did not terminate within {max_pages} pages; collected {len(seen)} ids")


class TestTheWalkInvariant:
    """Walk the whole board: exactly counts.total ids, no duplicates, no gaps."""

    async def test_a_project_walk_returns_every_row_exactly_once(self, mcp_client, db_manager):
        """THE acceptance test. 11 projects, page size 3, ties and the null boundary crossed.

        Board: 4 unfinished + 7 finished, of which 3 share one ``completed_at``. Ordered
        ``completed_at DESC NULLS FIRST, id ASC`` that is N,N,N,N | C,C,C(tied) | C,C,C,C --
        so with ``limit=3`` the page boundaries fall at rows 3, 6 and 9: inside the null
        region, ON the null boundary, and inside the tie group respectively. One walk
        exercises all three.
        """
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=4, finished=7, tie_size=3)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=PAGE, mode="triage"))
            total = first["counts"]["total"]
            assert total == len(seeded), f"counts.total disagrees with the seed: {total} vs {len(seeded)}"

            seen, pages = await _walk(
                client, "list_projects", "projects", "project_id", include_completed=True, limit=PAGE, mode="triage"
            )

            assert pages > 1, "the walk finished in one page -- the board is not exercising continuation"
            assert len(seen) == len(set(seen)), (
                f"the walk returned duplicates: {[i for i in seen if seen.count(i) > 1]!r}"
            )
            assert set(seen) == set(seeded), (
                f"the walk is not the whole board -- missing {sorted(set(seeded) - set(seen))!r}, "
                f"unexpected {sorted(set(seen) - set(seeded))!r}"
            )
            assert len(seen) == total, f"the walk returned {len(seen)} rows against counts.total={total}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_project_walk_one_row_per_page_returns_every_row(self, mcp_client, db_manager):
        """``limit=1``: EVERY page boundary is a tie or the null boundary.

        Item 1 measured that the smaller the page, the larger the silent loss -- a one-row
        page over a tie group returned 1 of 5 rows and reported completion. So the tightest
        page is the strongest regression test this feature has.
        """
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=3, finished=4, tie_size=4)

        try:
            seen, pages = await _walk(
                client, "list_projects", "projects", "project_id", include_completed=True, limit=1, mode="triage"
            )
            assert pages >= len(seeded), f"expected at least one page per row, got {pages} for {len(seeded)} rows"
            assert len(seen) == len(set(seen)), f"duplicates: {[i for i in seen if seen.count(i) > 1]!r}"
            assert set(seen) == set(seeded), f"missing {sorted(set(seeded) - set(seen))!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_task_walk_returns_every_row_exactly_once(self, mcp_client, db_manager):
        """The task list, whose whole board is ONE tie group.

        Every task is written in one transaction, so every ``created_at`` is identical and
        ``id`` carries the entire walk. If the keyset lost its tiebreak this returns one
        page and claims to be finished.
        """
        client, tenant_key = mcp_client
        seeded = await _seed_tasks(db_manager, tenant_key, count=11)

        try:
            seen, pages = await _walk(client, "list_tasks", "tasks", "task_id", limit=PAGE, mode="index")

            assert pages > 1, "the walk finished in one page -- the board is not exercising continuation"
            assert len(seen) == len(set(seen)), f"duplicates: {[i for i in seen if seen.count(i) > 1]!r}"
            assert set(seen) == set(seeded), f"missing {sorted(set(seeded) - set(seen))!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_default_creation_axis_walk_returns_every_row(self, mcp_client, db_manager):
        """The OTHER project axis: no ``include_completed``, so ``created_at DESC, id ASC``.

        ``list_projects`` picks its ordering from the caller's question, so a cursor issued
        against the fallback axis has to work too -- and it is a different keyset with no
        NULL region. Seeded unfinished-only so the default active-lifecycle filter returns
        them all.
        """
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=8, finished=0, tie_size=0)

        try:
            seen, _ = await _walk(client, "list_projects", "projects", "project_id", limit=PAGE, mode="triage")
            assert len(seen) == len(set(seen)), f"duplicates: {[i for i in seen if seen.count(i) > 1]!r}"
            assert set(seen) == set(seeded), f"missing {sorted(set(seeded) - set(seen))!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_without_a_cursor_the_same_call_never_advances(self, mcp_client, db_manager):
        """THE NEGATIVE CONTROL: repeating the call WITHOUT a cursor returns the same page forever.

        Without this, every walk assertion above is ambiguous -- a board that happened to fit
        one page, or a loop that terminated for some other reason, would read as a working
        cursor. This pins that the token is what advances the walk and nothing else: two
        identical un-cursored calls return the IDENTICAL first page, so progress is
        attributable to the cursor alone.
        """
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=3, finished=4, tie_size=4)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=PAGE, mode="triage"))
            again = _payload(await _call(client, "list_projects", include_completed=True, limit=PAGE, mode="triage"))
            assert [p["project_id"] for p in first["projects"]] == [p["project_id"] for p in again["projects"]], (
                "two identical un-cursored calls returned different pages, so this suite cannot "
                "attribute the walk's progress to the cursor"
            )
            assert first["truncated"] is True, (
                "the board must be larger than one page for this control to mean anything"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestBackwardCompatibility:
    """A call with no cursor must behave exactly as it does today."""

    async def test_a_call_without_a_cursor_is_unchanged(self, mcp_client, db_manager):
        """No ``cursor`` -> the shipped response, and NO ``next_cursor`` when nothing was cut.

        The pre-ruling is that a call with no cursor behaves byte-identically to today. The
        observable halves of that: the first page still returns ``limit`` rows with the
        shipped keys, and an UNtruncated response carries no continuation token at all --
        because a token on a complete answer would tell an agent to keep walking a set it
        has already finished.
        """
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=2, finished=2, tie_size=2)

        try:
            bounded = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            assert bounded["count"] == 2
            assert bounded["truncated"] is True
            assert "next_cursor" in bounded["truncation"]

            complete = _payload(await _call(client, "list_projects", include_completed=True, limit=50, mode="triage"))
            assert complete["count"] == len(seeded)
            assert complete["truncated"] is False
            assert "truncation" not in complete, (
                "an untruncated response must carry no truncation block at all, and therefore no "
                f"continuation token: {complete.get('truncation')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_next_cursor_appears_only_inside_the_truncation_block(self, mcp_client, db_manager):
        """The token lives INSIDE ``truncation``, never as a second top-level key.

        Pre-ruled, and structural rather than stylistic: a second vocabulary would make one
        tool report two shapes, and a caller that already reads ``truncation`` to learn its
        answer was cut would not see the remedy.
        """
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=2, finished=3, tie_size=3)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            assert "next_cursor" not in payload, "next_cursor must not be a top-level response key"
            assert payload["truncation"]["next_cursor"]
            # The shipped five keys are all still there -- extended, not replaced.
            for key in ("reason", "ceiling", "rows_fetched", "dropped", "advice"):
                assert key in payload["truncation"], f"the shipped truncation key {key!r} is gone"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_advice_names_the_token_when_one_exists(self, mcp_client, db_manager):
        """A cut with a token must SAY so in ``advice``, leading with it.

        ``advice`` is the field an agent acts on. "There is more, narrow your query" tells a
        caller to want less; the token answers the question it actually asked, so it goes
        first.
        """
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=2, finished=3, tie_size=3)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            advice = payload["truncation"]["advice"]
            assert "next_cursor" in advice, f"advice does not name the continuation token: {advice!r}"
            assert advice.startswith("There is more"), f"advice does not lead with the continuation remedy: {advice!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTheFilterFingerprintRefusal:
    """A token replayed under different filters is REFUSED, never silently answered."""

    async def test_replaying_a_cursor_under_changed_filters_is_refused(self, mcp_client, db_manager):
        """Change a filter mid-walk -> a structured rejection naming the remedy.

        This is the property that makes the token safe to hand an agent. Honouring it
        instead would return rows that are neither the new filter's rows nor a complete walk
        of anything, and report success -- the defect class this whole read layer exists to
        remove.
        """
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=3, finished=4, tie_size=4)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token = first["truncation"]["next_cursor"]

            # Same token, a DIFFERENT filter set (a query filter added).
            replayed = _payload(
                await _call(
                    client,
                    "list_projects",
                    include_completed=True,
                    limit=2,
                    mode="triage",
                    query="finished",
                    cursor=token,
                )
            )
            assert replayed.get("success") is False, (
                f"a cross-filter replay was answered instead of refused: {replayed!r}"
            )
            assert replayed.get("error") in {"CURSOR_FILTER_MISMATCH", "CURSOR_AXIS_MISMATCH"}, (
                f"unexpected rejection code: {replayed.get('error')!r}"
            )
            assert "restart" in replayed.get("message", "").lower(), (
                f"the refusal must name the remedy: {replayed.get('message')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_garbage_cursor_is_refused_with_a_remedy(self, mcp_client, db_manager):
        """A token this server never issued is refused, not guessed at."""
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=2, finished=2, tie_size=2)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, cursor="not-a-token"))
            assert payload.get("success") is False, f"a garbage cursor was accepted: {payload!r}"
            assert payload.get("error", "").startswith("CURSOR_")
            assert "restart" in payload.get("message", "").lower()
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_refused_cursor_is_a_response_and_not_an_error(self, mcp_client, db_manager):
        """The refusal must reach the agent as normal tool content, NOT as ``isError``.

        The BE-6081 Tier-2 contract: a deliberate, agent-actionable domain rejection RETURNS
        a structured dict and does not raise. A refused cursor is something the agent can fix
        by restarting the walk, so it should arrive with a remedy it can read rather than as
        a transport error it has to interpret.
        """
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=2, finished=2, tie_size=2)

        try:
            result = await _call(client, "list_projects", include_completed=True, cursor="not-a-token")
            assert not result.is_error, (
                "a refused cursor came back as isError; it must be a Tier-2 structured "
                f"rejection on the success path. content: {_content_text(result)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_changing_only_the_page_size_mid_walk_is_allowed(self, mcp_client, db_manager):
        """``limit`` and ``mode`` are NOT part of the fingerprint, deliberately.

        They change how many rows a page holds and how fat each row is -- not which rows
        exist or in what order. An agent that walks in ``mode='triage'`` and pulls one page
        richer is doing something reasonable, and refusing it would be a page-size bound
        pretending to be a correctness check. The both-sides guard for the refusal above:
        without this, "refuse everything" would read as green.
        """
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=3, finished=4, tie_size=4)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token = first["truncation"]["next_cursor"]
            seen = [p["project_id"] for p in first["projects"]]

            # Same filters, DIFFERENT limit and mode.
            second = _payload(
                await _call(client, "list_projects", include_completed=True, limit=4, mode="planning", cursor=token)
            )
            assert second.get("success") is not False, f"a limit/mode change was refused: {second!r}"
            seen.extend(p["project_id"] for p in second["projects"])
            assert len(seen) == len(set(seen)), f"the mid-walk mode change repeated rows: {seen!r}"
            assert set(seen) <= set(seeded)
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTheTokenCarriesNoTenantKey:
    """Tenant safety: the token is a position, never an authority."""

    async def test_a_cursor_from_another_tenant_cannot_read_across_the_boundary(self, mcp_client, db_manager):
        """A token minted in tenant A, replayed in tenant B, returns only B's rows.

        The token is base64 and unsigned, so it is forgeable by design -- the safety comes
        from what it is USED for. Its decoded values become operands in a WHERE comparison;
        the row is never fetched by id and no field of it is echoed, and every query still
        filters ``tenant_key`` server-side. This asserts the observable consequence rather
        than the intention.
        """
        client, tenant_a = mcp_client
        tenant_b = TenantManager.generate_tenant_key()
        a_ids = await _seed_projects(db_manager, tenant_a, unfinished=2, finished=3, tie_size=3)
        b_ids = await _seed_projects(db_manager, tenant_b, unfinished=2, finished=3, tie_size=3)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token_from_a = first["truncation"]["next_cursor"]

            # The fixture pins the transport to tenant A, so replay A's token there and
            # assert the result is bounded by A's board -- B's ids must be unreachable
            # through it no matter what position the token names.
            replayed = _payload(
                await _call(
                    client, "list_projects", include_completed=True, limit=50, mode="triage", cursor=token_from_a
                )
            )
            returned = {p["project_id"] for p in replayed.get("projects", [])}
            assert returned <= set(a_ids), f"a cursor reached rows outside its own tenant: {returned - set(a_ids)!r}"
            assert not (returned & set(b_ids)), "a cursor crossed the tenant boundary"
        finally:
            await purge_tenant_rows(db_manager, tenant_a)
            await purge_tenant_rows(db_manager, tenant_b)

    async def test_the_token_does_not_contain_the_tenant_key(self, mcp_client, db_manager):
        """Decoded, the token must carry no tenant key -- asserted on the token itself.

        A value that must never be trusted is better absent than present-and-ignored: a
        tenant key inside the token would be a field a future reader could plausibly start
        reading, and the first time anyone did, the isolation boundary would move into an
        agent-supplied string.
        """
        import base64

        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=2, finished=3, tie_size=3)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token = payload["truncation"]["next_cursor"]
            decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
            assert tenant_key not in decoded, f"the token carries the tenant key: {decoded!r}"
            assert "tenant" not in decoded.lower(), f"the token carries a tenant field: {decoded!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestALongFilteredRunDoesNotStallTheWalk:
    """The case where a whole fetch window is rejected by a Python filter.

    ``list_projects`` applies several filters in Python AFTER the SQL fetch, so a page can
    come back ceiling-bounded and be emptied entirely before the caller sees anything. The
    naive cursor rule -- "take the position from the last row RETURNED" -- has no row to take
    it from there, so the response would carry ``truncated: true`` with no ``next_cursor``
    and the walk would stall. Truncated-and-cursorless is unactionable, which is the same
    silent-dead-end family this whole read layer exists to remove.

    So the token falls back to the last row FETCHED when the FILTERS are what emptied the
    page. Safe because every fetched row was examined and rejected under this filter set --
    and sound only because the filter fingerprint guarantees any continuation arrives under
    the SAME set.
    """

    async def test_a_whole_rejected_window_between_two_matches_is_crossed(self, mcp_client, db_manager, monkeypatch):
        """Two matching rows separated by a full ceiling-window of filter-rejected rows.

        The ceiling is patched small (the constant IS the mechanism, so a tiny board against
        a ceiling of 2 exercises the identical path a huge board would at production scale)
        and the filter is ``created_after``, which runs in Python after the fetch and reads a
        DIFFERENT column from the one the list is ordered by. Between the two matching rows
        sit six rows the filter rejects -- three full ceiling-windows of nothing.

        Asserts all three things that could go wrong: the walk TERMINATES (no stall, no
        loop), it collects BOTH matching rows, and it collects nothing else.
        """
        from giljo_mcp.services.project_service import _mcp_adapter_query_mixin as ceiling_mod

        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 2)
        wanted = await _seed_filtered_run(db_manager, tenant_key)

        try:
            seen, pages = await _walk(
                client,
                "list_projects",
                "projects",
                "project_id",
                include_completed=True,
                limit=5,
                mode="triage",
                created_after=_KEEP_CREATED_AFTER,
                max_pages=30,
            )
            assert pages > 1, "the run was crossed in one page -- the rejected window is not being exercised"
            assert set(seen) == set(wanted), (
                "the walk did not cross a fully filter-rejected window: expected exactly "
                f"{sorted(wanted)!r}, got {sorted(set(seen))!r}"
            )
            assert len(seen) == len(set(seen)), f"the walk repeated rows while crossing the run: {seen!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTheCursorPositionComesFromTheModelNotTheProjection:
    """The token for a given row must be MODE-INDEPENDENT."""

    async def test_the_same_row_yields_the_same_token_in_every_mode(self, mcp_client, db_manager):
        """A cursor is a POSITION, so the projection must not be able to change it.

        **This assertion replaced one built on a false premise, and the correction is the
        point.** The first version asserted that ``mode='triage'`` omits ``completed_at`` from
        its row, and used that to justify reading the position off the ORM model. Measured:
        **the triage row DOES carry ``completed_at``** -- the premise was wrong, and it was
        only caught because the test stated it out loud instead of assuming it.

        The property that IS true, and is the real reason to read the model: every projection
        SERIALIZES the value, so a token built from the row would depend on a formatting
        choice the projection owns and on the field continuing to be projected. Reading the
        column off the model makes the token identical for the same row in every mode -- which
        is precisely what lets ``mode`` stay out of the filter fingerprint and a mid-walk mode
        change stay legal. Two calls differing ONLY in ``mode`` must mint the same token.
        """
        client, tenant_key = mcp_client
        # 1 unfinished + 4 finished at limit=3 -> page one ends on a FINISHED row, so the
        # position is a real timestamp rather than the legitimate null of the NULLs region.
        await _seed_projects(db_manager, tenant_key, unfinished=1, finished=4, tie_size=4)

        try:
            triage = _payload(await _call(client, "list_projects", include_completed=True, limit=3, mode="triage"))
            planning = _payload(await _call(client, "list_projects", include_completed=True, limit=3, mode="planning"))

            assert [p["project_id"] for p in triage["projects"]] == [p["project_id"] for p in planning["projects"]], (
                "the two modes returned different rows, so their tokens are not comparable"
            )
            assert triage["truncation"]["next_cursor"] == planning["truncation"]["next_cursor"], (
                "the same row minted DIFFERENT tokens in two modes, so the position is coming "
                "from the projection rather than the model -- which would make a mid-walk mode "
                "change silently reposition the walk"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_position_is_a_real_timestamp_and_the_walk_completes(self, mcp_client, db_manager):
        """Decode a real token: the position must be a parseable timestamp, and it must work.

        Asserted on the decoded token (the observable) rather than on the code that built it,
        and paired with an actual continuation -- a position that decodes but does not page is
        not a position.
        """
        import base64

        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=1, finished=4, tie_size=4)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, limit=3, mode="triage"))
            token = payload["truncation"]["next_cursor"]
            decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            assert decoded["s"] is not None, f"the cursor carries no position: {decoded!r}"
            datetime.fromisoformat(decoded["s"])  # raises if it is not a real timestamp

            seen = [p["project_id"] for p in payload["projects"]]
            second = _payload(
                await _call(client, "list_projects", include_completed=True, limit=3, mode="triage", cursor=token)
            )
            assert second.get("success") is not False, f"the token was refused: {second!r}"
            seen.extend(p["project_id"] for p in second["projects"])
            assert len(seen) == len(set(seen)) == 5, f"the walk did not reach the whole board: {seen!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


def _delete_s_key(token: str) -> str:
    """Re-mint ``token`` with its ``s`` (position) key removed entirely.

    Not ``"s": null`` -- the JSON key itself is absent, which ``payload.get("s")`` cannot
    tell apart from an explicit null but which the real minter never produces (BE-9469 QA
    follow-up, U50-F1).
    """
    import base64

    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    del payload["s"]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


class TestAMissingPositionKeyIsRefusedNotCrashed:
    """U50-F1 -- a cursor with the ``s`` key deleted entirely must be a structured refusal.

    Every other malformed-token shape (garbage base64, wrong version, bad axis, wrong
    fingerprint, a non-timestamp ``s``) already reaches the agent as a clean
    ``CURSOR_MALFORMED``-family rejection with a followable remedy. A token whose ``s`` key
    is missing outright took a different, uncaught path and reached the agent as the
    generic ``isError`` internal-failure message instead -- the one cursor shape that told
    the caller nothing about how to get unstuck.
    """

    async def test_list_projects_refuses_rather_than_crashes(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=3, finished=0, tie_size=0)

        try:
            first = _payload(await _call(client, "list_projects", limit=1, mode="triage"))
            real_token = first["truncation"]["next_cursor"]
            crafted = _delete_s_key(real_token)

            result = await _call(client, "list_projects", limit=1, mode="triage", cursor=crafted)
            assert not result.is_error, (
                "a cursor missing its 's' key crashed the transport instead of being refused "
                f"as a structured rejection: {_content_text(result)!r}"
            )
            payload = _payload(result)
            assert payload.get("success") is False, f"a cursor missing 's' was silently accepted: {payload!r}"
            assert payload.get("error", "").startswith("CURSOR_"), (
                f"unexpected rejection code for a missing 's' key: {payload!r}"
            )
            assert "restart" in payload.get("message", "").lower(), (
                f"the refusal must name the remedy, same as every other malformed-token case: {payload!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_list_tasks_refuses_rather_than_crashes(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        await _seed_tasks(db_manager, tenant_key, count=3)

        try:
            first = _payload(await _call(client, "list_tasks", limit=1, mode="index"))
            real_token = first["truncation"]["next_cursor"]
            crafted = _delete_s_key(real_token)

            result = await _call(client, "list_tasks", limit=1, mode="index", cursor=crafted)
            assert not result.is_error, (
                "a cursor missing its 's' key crashed the transport instead of being refused "
                f"as a structured rejection: {_content_text(result)!r}"
            )
            payload = _payload(result)
            assert payload.get("success") is False, f"a cursor missing 's' was silently accepted: {payload!r}"
            assert payload.get("error", "").startswith("CURSOR_"), (
                f"unexpected rejection code for a missing 's' key: {payload!r}"
            )
            assert "restart" in payload.get("message", "").lower(), (
                f"the refusal must name the remedy, same as every other malformed-token case: {payload!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestMatchedIsConstantAndRemainingDecreases:
    """U47-F2 -- ``matched`` must mean the SAME thing on every page of a walk.

    Pre-fix, ``counts.matched`` was the cursor-scoped fetch count: 471 on page 1 of a
    board that size, then 371, 271... on later pages -- the whole-filter-set count on
    page 1 only, and "rows still ahead of the cursor" everywhere else. The fix: keep
    ``matched`` constant (the whole-filter-set count, cursor excluded) and add
    ``remaining`` for the quantity that legitimately shrinks.
    """

    async def test_list_projects_matched_holds_remaining_shrinks(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=11, finished=0, tie_size=0)

        try:
            table: list[tuple[int, Any, Any, int]] = []
            cursor = ""
            seen: list[str] = []
            for _ in range(10):
                payload = _payload(await _call(client, "list_projects", limit=3, mode="triage", cursor=cursor))
                counts = payload["counts"]
                returned = len(payload["projects"])
                table.append((counts["total"], counts.get("matched"), counts.get("remaining"), returned))
                seen.extend(p["project_id"] for p in payload["projects"])
                if not payload.get("truncated"):
                    break
                cursor = payload["truncation"]["next_cursor"]

            assert len(table) >= 4, f"the walk finished in too few pages to exercise the drift: {table!r}"
            matched_values = {row[1] for row in table}
            assert len(matched_values) == 1, f"'matched' is not constant across the walk: {table!r}"
            assert table[0][1] == len(seeded), f"page 1 'matched' must be the whole-filter-set count: {table!r}"
            assert table[0][1] == table[0][2], f"page 1 must have matched == remaining: {table!r}"
            remaining_seq = [row[2] for row in table]
            expected = [len(seeded) - sum(row[3] for row in table[:i]) for i in range(len(table))]
            assert remaining_seq == expected, (
                f"'remaining' must decrease by exactly 'returned' each page: got {table!r}, expected "
                f"remaining sequence {expected!r}"
            )
            assert set(seen) == set(seeded) and len(seen) == len(set(seen)), f"the walk lost rows: {table!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_list_tasks_matched_holds_remaining_shrinks(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        seeded = await _seed_tasks(db_manager, tenant_key, count=11)

        try:
            table: list[tuple[int, Any, Any, int]] = []
            cursor = ""
            seen: list[str] = []
            for _ in range(10):
                payload = _payload(await _call(client, "list_tasks", limit=3, mode="index", cursor=cursor))
                counts = payload["counts"]
                returned = len(payload["tasks"])
                table.append((counts["total"], counts.get("matched"), counts.get("remaining"), returned))
                seen.extend(t["task_id"] for t in payload["tasks"])
                if not payload.get("truncated"):
                    break
                cursor = payload["truncation"]["next_cursor"]

            assert len(table) >= 4, f"the walk finished in too few pages to exercise the drift: {table!r}"
            matched_values = {row[1] for row in table}
            assert len(matched_values) == 1, f"'matched' is not constant across the walk: {table!r}"
            assert table[0][1] == len(seeded), f"page 1 'matched' must be the whole-filter-set count: {table!r}"
            assert table[0][1] == table[0][2], f"page 1 must have matched == remaining: {table!r}"
            remaining_seq = [row[2] for row in table]
            expected = [len(seeded) - sum(row[3] for row in table[:i]) for i in range(len(table))]
            assert remaining_seq == expected, (
                f"'remaining' must decrease by exactly 'returned' each page: got {table!r}, expected "
                f"remaining sequence {expected!r}"
            )
            assert set(seen) == set(seeded) and len(seen) == len(set(seen)), f"the walk lost rows: {table!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)
