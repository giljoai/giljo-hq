# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9468 -- the agent-facing task list has no bound of any kind, and no way to size itself.

The defect is not "the list is big". It is that **nothing tells a caller how big the
answer will be before it asks for it.** An agent asked "what did we ship" cannot know
whether that is 5 rows or 5,000, so it asks for everything and hopes. ``list_tasks``
then answers with the whole corpus: no row cap, no size cap, no truncation signal, and
in ``full`` mode with ``description`` untruncated unless ``memory_limit`` is passed.

Four moves, in dependency order, and the first is the keystone:

1. **counts** -- totals by status and by type plus the created-at span, on EVERY
   response. One GROUP BY. The agent learns the shape of the board *before* choosing
   what to ask for. A size ceiling truncates the guess; it does not improve it.
2. **a bounded ``limit``** -- a sane default and a hard max, copying the contract
   ``search_memory`` already ships (``SEARCH_MEMORY_LIMIT_DEFAULT`` /
   ``SEARCH_MEMORY_LIMIT_MAX``). Asking for everything stays possible; it becomes a
   deliberate request rather than the accidental default.
3. **a genuinely lean index row** -- and a test that asserts it is leaner **on measured
   bytes**, because that exact claim is documented and false on the sibling tool.
4. **``query``** -- substring search over title/description. There is no text search
   over tasks on the MCP surface at all today, and "the OAuth one" is how users actually
   refer to work.

Plus the backstop underneath all four: a **response-size ceiling in characters**,
enforced by dropping whole **ROWS, never fields**. Dropping fields is the wrong shape
for a list -- a half-row is not a usable answer, and the in-repo field-trimmer protects
the display label while discarding the identifier the agent needs in order to act.

FAIL-FIRST, measured on base master ``048e65df65b2161aaadc880c8def8aec2f264386``.
Every RED below is an **assertion** failing on a value the server returned, never an
import error, a missing fixture, or a patched-in constant that does not exist yet --
a broken instrument that goes red is not a reproduction:

* every test in ``TestTheCountsBlockIsTheKeystone``     -- ``counts`` absent entirely.
* ``test_the_default_response_is_bounded``              -- all 60 seeded rows come back.
* ``test_a_bounded_response_says_so``                   -- ``truncated`` absent.
* ``test_the_limit_can_be_raised_to_ask_for_everything`` -- ``limit`` silently IGNORED, not
  rejected: on base master an unknown parameter is absorbed and the whole board returned.
* ``test_the_limit_is_capped_at_a_hard_maximum``        -- same; no bound to exceed.
* ``test_the_size_backstop_drops_whole_rows``           -- 185,535 chars, no size bound at all.
* ``test_the_index_row_is_actually_leaner_in_bytes``    -- ``mode='index'`` rejected.
* both tests in ``TestQueryIsARealVerb``                -- ``query`` silently ignored.

Everything in ``TestNothingThatWorksTodayStopsWorking`` is a BOTH-SIDES GUARD: those pass
BEFORE and AFTER the change. **They all passed on base master while eleven others failed**,
which is what proves the red above was the assertion and not a broken harness.

Two tests here are guards rather than reproductions, and say so in their own docstrings:
``test_rows_tied_on_created_at_are_cut_on_a_documented_total_order`` (the un-tiebroken
query could not be made to misbehave, so it asserts the discriminating property instead)
and ``test_the_biggest_row_the_tool_can_create_still_fits``.

Transport: the REAL ``@mcp.tool`` transport via ``create_connected_server_and_client_session``
against real Postgres -- the boundary an agent client actually hits, per the house rule
that a bug gets its regression test at the layer it lived on.

Parallel-safe: each test generates a fresh ``tenant_key`` and purges its own rows in a
``finally``; these MCP-adapter calls commit for real through ``db_manager``, so there is
no rollback isolation to lean on. No module-level mutable state, no ordering
dependencies.

Edition Scope: Both.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


# The numbers this suite asserts against are stated as literals, NOT imported from the
# module under test. Importing them would make the assertions tautological -- they would
# follow the constant wherever it drifted and could never fail. These are the values the
# change is required to ship; if the constant moves, this test is the thing that argues
# about it.
EXPECTED_DEFAULT_LIMIT = 50
EXPECTED_MAX_LIMIT = 500
EXPECTED_CHAR_CEILING = 48_000


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _content_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def mcp_client(db_manager, monkeypatch):
    """Wire a real ToolAccessor into the in-memory MCP transport.

    No injected test session: every tool call opens its own real session, exactly as it
    does in production. Yields ``(client_factory, tenant_key)``.
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


async def _seed(
    db_manager,
    tenant_key: str,
    rows: list[dict],
) -> str:
    """Commit one active product, the reserved TSK taxonomy row, and the given tasks.

    Rows are inserted directly rather than through ``create_task_for_mcp`` because that
    path takes the shared global serial counter's advisory lock once per task; at 60+
    rows that dominates the runtime of the suite and exercises nothing this test is about.
    Each row dict carries ``title``, ``status``, ``priority``, ``description`` and an
    ``age_days`` offset used to build a deterministic ``created_at`` span.
    """
    product_id = str(uuid.uuid4())
    task_type_id = str(uuid.uuid4())
    base = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"Task read-layer product {uuid.uuid4().hex[:6]}",
                description="Seeded for the task read-layer reproduction.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            TaxonomyType(
                id=task_type_id,
                tenant_key=tenant_key,
                abbreviation="TSK",
                label="Task",
                color="#607D8B",
                sort_order=0,
            )
        )
        for index, row in enumerate(rows, start=1):
            session.add(
                Task(
                    id=row.get("id") or str(uuid.uuid4()),
                    tenant_key=tenant_key,
                    product_id=product_id,
                    task_type_id=task_type_id,
                    title=row["title"],
                    description=row.get("description", "Seeded task description."),
                    status=row.get("status", "pending"),
                    priority=row.get("priority", "medium"),
                    taxonomy_alias=f"TSK-{9000 + index}",
                    series_number=9000 + index,
                    hidden=False,
                    created_at=base - timedelta(days=row.get("age_days", index)),
                )
            )
        await session.commit()

    return product_id


def _corpus(n: int) -> list[dict]:
    """``n`` tasks across a realistic status/priority spread.

    Title and description lengths are taken from REAL rows read (bounded, read-only) off
    the live board rather than invented: the three open tasks there carry 95-, 111- and
    133-character titles, so a ~110-character title is the honest middle, not a
    flattering short one.
    """
    statuses = ["completed", "completed", "completed", "pending", "in_progress", "blocked"]
    priorities = ["low", "medium", "high", "critical"]
    return [
        {
            "title": (
                f"Task {i:04d} -- reproduce the agent-facing read-layer bound and prove the "
                "response says how much it withheld"
            ),
            "description": "A seeded description standing in for the real prose body. " * 4,
            "status": statuses[i % len(statuses)],
            "priority": priorities[i % len(priorities)],
            "age_days": i,
        }
        for i in range(n)
    ]


async def _list_tasks(client, **kwargs) -> object:
    """Invoke the agent-facing ``list_tasks`` @mcp.tool over the real transport."""
    async with client() as mcp_session:
        return await mcp_session.call_tool("list_tasks", kwargs)


def _wire_chars(payload: dict) -> int:
    """Bytes as the MCP wire actually serializes them.

    ``pydantic_core.to_json(data, fallback=str).decode()`` is the real serializer
    (``fastmcp/tools/base.py``) and it emits COMPACT JSON. Measuring with
    ``json.dumps`` defaults inflates the number with separator whitespace that never
    goes over the wire, which is how a size assertion talks itself into passing.
    """
    from pydantic_core import to_json

    return len(to_json(payload, fallback=str).decode())


# ---------------------------------------------------------------------------
# 1. The keystone: counts
# ---------------------------------------------------------------------------


class TestTheCountsBlockIsTheKeystone:
    async def test_every_response_carries_a_counts_block(self, mcp_client, db_manager):
        """Without this, every other rule is the model guessing.

        An agent cannot choose a sensible ``limit``, or decide whether to filter at all,
        until it knows the board is 1,069 completed and 3 active rather than 12 rows
        total. This is the cheapest possible answer to that question -- one GROUP BY --
        and it is why it ships on EVERY response rather than behind a flag: a signal you
        have to know to ask for does not solve a problem whose whole shape is not knowing
        what to ask for.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(12))

        try:
            result = await _list_tasks(client)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)

            counts = payload.get("counts")
            assert isinstance(counts, dict), (
                "every list_tasks response must carry a counts block so the caller can size "
                f"the board BEFORE choosing what to ask for; got counts={counts!r}. "
                f"response keys present: {sorted(payload)!r}"
            )
            assert counts.get("scope") == "product", (
                "the block must name the population it describes -- this list is scoped to the "
                f"ACTIVE PRODUCT, not the tenant, so a bare total is ambiguous. got {counts!r}"
            )
            assert counts.get("total") == 12, f"counts.total must state the whole board, got {counts!r}"
            assert counts.get("matched") == 12, f"counts.matched must state what the filters hit, got {counts!r}"
            assert counts.get("returned") == 12, f"counts.returned must state the rows in hand, got {counts!r}"
            assert counts["returned"] == payload["count"], (
                "counts.returned must be ASSIGNED from the shipped count, never recomputed -- "
                f"two independent len() calls are how a mirrored field drifts. got {counts!r}"
            )
            assert counts.get("by_type", {}).get("TSK") == 12, (
                f"counts.by_type must total by taxonomy abbreviation, got {counts.get('by_type')!r}"
            )

            # A CLOSED enum, so every status is present with an explicit zero. An absent
            # key cannot be told apart from "this server does not report that status",
            # which is the absent-versus-false defect BE-9455 Symptom A removed.
            by_status = counts.get("by_status", {})
            assert set(by_status) == {"pending", "in_progress", "completed", "blocked", "cancelled"}, (
                f"by_status must carry EXPLICIT ZEROS for the whole status vocabulary, got {by_status!r}"
            )
            assert by_status["completed"] == 6, f"by_status must total by status, got {by_status!r}"
            assert by_status["cancelled"] == 0, (
                f"a status with no rows must be present and zero, not missing, got {by_status!r}"
            )
            assert sum(by_status.values()) == counts["total"], (
                f"the parts must sum to the whole, got {by_status!r} against total {counts['total']}"
            )

            span = counts.get("date_span", {})
            assert set(span) == {"created_first", "created_last", "completed_first", "completed_last"}, (
                f"date_span must carry all four keys so the shape matches the sibling tool, got {span!r}"
            )
            assert span["created_first"] < span["created_last"], (
                f"the span must be ordered earliest-first, got {span!r}"
            )
            assert span["completed_first"] is None and span["completed_last"] is None, (
                "with no completed_at stamped, the completion bounds are explicit NULLs rather "
                f"than missing keys -- same absent-versus-false rule. got {span!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_by_type_omits_absent_types_while_by_status_does_not(self, mcp_client, db_manager):
        """The two maps are asymmetric ON PURPOSE, and the asymmetry is the design.

        ``by_status`` keys a CLOSED enum the caller can enumerate independently, so a
        missing key is ambiguous and must never happen -- explicit zeros.
        ``by_type`` keys an OPEN, tenant-configured vocabulary the caller cannot
        enumerate, so an absent key claims nothing about anything, and emitting every
        configured type at zero would be pure noise in a block whose whole value is being
        small enough to ship on every response.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(6))

        try:
            counts = _payload(await _list_tasks(client))["counts"]
            assert counts["by_type"] == {"TSK": 6}, (
                f"by_type carries only the types that exist on this board, got {counts['by_type']!r}"
            )
            assert 0 in counts["by_status"].values(), f"by_status keeps its zeros, got {counts['by_status']!r}"
            assert 0 not in counts["by_type"].values(), f"by_type carries no zero entries, got {counts['by_type']!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_counts_are_of_the_whole_board_not_the_page(self, mcp_client, db_manager):
        """THE test that makes counts worth shipping, and the easiest thing to get wrong.

        Counting the rows already in hand is free and useless -- it tells the agent the
        size of the answer it can already see. The number that changes a decision is the
        one it CANNOT see. ``get_context(['tasks'])`` ships that exact defect today: its
        ``open_count`` is ``len(rows_after_limit)``, so a truncated list reports the
        truncated count as though it were the total.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(20))

        try:
            payload = _payload(await _list_tasks(client, limit=5))
            counts = payload.get("counts")
            assert isinstance(counts, dict), f"counts block absent; response keys: {sorted(payload)!r}"
            assert len(payload["tasks"]) == 5, f"the page should hold 5 rows, got {len(payload['tasks'])}"
            assert counts.get("total") == 20, (
                "counts must describe the WHOLE board, not the page in hand -- a count of the "
                f"rows already returned tells the caller nothing it did not know. got {counts!r}"
            )
            assert counts.get("returned") == 5, f"counts.returned is the page, got {counts!r}"
            assert counts.get("matched") == 20, f"no filters were passed, so matched equals the board, got {counts!r}"
            # The invariant a caller can check for itself, and the reason `matched` earns
            # its place: "there is more" becomes "there is exactly this much more".
            assert (payload.get("truncated") is True) == (counts["returned"] < counts["matched"]), (
                f"truncated must hold iff returned < matched. truncated={payload.get('truncated')!r}, "
                f"returned={counts['returned']}, matched={counts['matched']}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_matched_reflects_the_filters_even_though_total_does_not(self, mcp_client, db_manager):
        """``total`` and ``matched`` answer different questions, and both are needed.

        ``total`` says how big the board is -- the thing the caller cannot see. ``matched``
        says how much of it the caller's own query hit -- "your search found 2 of 12" --
        which is what decides whether to narrow further or widen. Reporting only one of
        them leaves the caller guessing about the other.

        On this tool ``matched`` is EXACT by construction: there is no defensive ceiling
        to bound the fetch, and every filter is applied in SQL, so a COUNT carrying the
        same predicates can neither understate nor overstate.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(12))

        try:
            counts = _payload(await _list_tasks(client, status="pending"))["counts"]
            assert counts["total"] == 12, f"the board is unchanged by a filter, got {counts!r}"
            assert counts["matched"] == 2, f"the filter hit 2 of 12, got {counts!r}"
            assert counts["returned"] == 2, f"and both were returned, got {counts!r}"

            narrowed = _payload(await _list_tasks(client, query="no-such-text-anywhere"))["counts"]
            assert narrowed["total"] == 12, f"a query must not shrink the board figure, got {narrowed!r}"
            assert narrowed["matched"] == 0, f"a query matching nothing reports 0 matched, got {narrowed!r}"
            assert narrowed["returned"] == 0, f"and 0 returned, got {narrowed!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_counts_ignore_the_callers_own_filters(self, mcp_client, db_manager):
        """Counts describe the WHOLE board -- deliberately including what the filter excluded.

        The tempting design is to scope the counts to the caller's filter, so they describe
        "the question that was asked". That reproduces the defect inside the fix for it: a
        caller that filtered to ``status='pending'`` and is told "total: 2" learns nothing
        about the 1,000-row archive it just filtered away, which is precisely the thing it
        needed to know before choosing what to ask for next.

        So ``counts`` is scoped to tenant + active product and ignores ``status``,
        ``priority``, ``task_type``, ``due_before``, ``hidden``, ``query`` and ``limit``
        alike. The two numbers are separately named and neither one's meaning shifts with
        the call: shipped ``count`` is always the rows in THIS response, ``counts.total``
        is always the whole board.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(12))

        try:
            payload = _payload(await _list_tasks(client, status="pending"))
            counts = payload.get("counts")
            assert isinstance(counts, dict), f"counts block absent; response keys: {sorted(payload)!r}"
            assert payload["count"] == 2, f"the response holds the 2 pending rows, got {payload['count']}"
            assert counts.get("total") == 12, (
                "counts must describe the whole board even under a filter -- the archive the "
                f"caller filtered away is exactly what it could not otherwise see. got {counts!r}"
            )
            assert counts.get("by_status", {}).get("completed") == 6, (
                f"a status filter must not erase the other statuses from the counts, got {counts.get('by_status')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 2. A bounded limit, with the escape hatch intact
# ---------------------------------------------------------------------------


class TestTheListIsBounded:
    async def test_the_default_response_is_bounded(self, mcp_client, db_manager):
        """THE reproduction. Today this list has no bound of ANY kind.

        No row cap, no size cap, no truncation flag -- strictly worse than the sibling
        project list was before its own ceiling landed. 60 rows go in and 60 come back;
        6,000 would too.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(60))

        try:
            result = await _list_tasks(client)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            returned = len(payload["tasks"])

            assert returned <= EXPECTED_DEFAULT_LIMIT, (
                "list_tasks has NO bound of any kind: every seeded row came back. A caller "
                "that asks the default question must get a bounded answer. "
                f"seeded 60, returned {returned}, response keys: {sorted(payload)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_bounded_response_says_so(self, mcp_client, db_manager):
        """A cut the caller cannot detect is the silent half of the defect.

        Reuses the SHIPPED vocabulary rather than inventing a second one: ``truncated``
        always present, and a ``truncation`` detail block only when something was
        actually cut, carrying the existing ``{reason, ceiling, rows_fetched, dropped,
        advice}`` shape. ``reason`` is already a discriminator, so a limit cut simply
        adds a value to it.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(60))

        try:
            payload = _payload(await _list_tasks(client))

            assert payload.get("truncated") is True, (
                "a response that withheld rows must say so on the response body -- the caller "
                "is an agent in someone else's process that will never read our server log. "
                f"got truncated={payload.get('truncated')!r}"
            )
            note = payload.get("truncation")
            assert isinstance(note, dict), f"a bounded response must carry a truncation detail block, got {note!r}"
            assert note.get("reason") == "limit", f"the detail must name WHICH bound cut the list, got {note!r}"
            assert note.get("ceiling") == EXPECTED_DEFAULT_LIMIT, (
                f"the detail must name the bound that applied, got {note!r}"
            )
            assert note.get("rows_fetched") == EXPECTED_DEFAULT_LIMIT, (
                f"the detail must state how many rows survived, got {note!r}"
            )
            assert note.get("advice"), f"the detail must tell the caller what to do about it, got {note!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_limit_can_be_raised_to_ask_for_everything(self, mcp_client, db_manager):
        """Asking for everything must stay POSSIBLE -- it just stops being the accident.

        This is an explicit operator requirement, and it is the half of the change that
        is easy to lose: a bound that cannot be raised is not a default, it is a refusal.
        60 rows over a default of 50, requested deliberately, come back whole and
        unflagged.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(60))

        try:
            result = await _list_tasks(client, limit=200)
            assert not result.is_error, (
                "list_tasks does not accept a limit at all -- there is no way to ask for more "
                f"than the default, or to ask deliberately for everything. content: {_content_text(result)!r}"
            )
            payload = _payload(result)
            assert len(payload["tasks"]) == 60, (
                f"a deliberately raised limit must return the whole set, got {len(payload['tasks'])}"
            )
            assert payload.get("truncated") is False, (
                f"nothing was withheld, so the response must say so, got {payload.get('truncated')!r}"
            )
            assert "truncation" not in payload, (
                f"an untruncated response carries no detail block, got {payload.get('truncation')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_rows_tied_on_created_at_are_cut_on_a_documented_total_order(self, mcp_client, db_manager):
        """Which row a bound drops must be decided by a rule, not by storage order.

        ``created_at`` defaults to ``func.now()``, and PostgreSQL's ``now()`` is
        TRANSACTION-scoped, so every task created in one transaction carries a
        byte-identical timestamp. Ordered by ``created_at`` alone, those rows have no
        defined order at all.

        **That was harmless until this change and is not harmless after it.** While the
        list was unbounded, every tied row came back regardless of order. Adding
        ``limit`` is what makes tie-order decide WHICH row falls outside the window, so
        the sort needs a unique tiebreak to be a total order.

        **HONESTY NOTE, because the distinction matters: this is a GUARD, not a
        reproduction.** I could not make the un-tiebroken query return rows in a
        different order -- at this scale PostgreSQL returns them in heap order, which is
        stable in practice, and I am not going to claim a failure I did not observe. So
        the test does not assert "two calls agree" (that passed before the fix too, and
        proves nothing). It asserts the stronger, actually-discriminating property: the
        page is the prefix of the rows sorted by ``(created_at DESC, task_id ASC)``.
        Because the seeded ids are random UUIDs, heap order is not id-ascending, so
        removing the tiebreak DOES turn this red -- verified both ways before commit.

        Same root cause as the keyset defect on the thread repository, where a strict
        ``created_at <`` cursor with no unique tiebreak silently skips rows against the
        same transaction-scoped ``now()``. Different surface, one lesson: a sort that
        decides what to discard has to be a total order.
        """
        client, tenant_key = mcp_client
        # Every row identical in created_at -- seeded in ONE transaction at ONE explicit
        # timestamp, which is exactly the shape func.now() produces in production.
        tied = [{"title": f"Tied row {i:03d}", "status": "pending", "age_days": 0} for i in range(30)]
        await _seed(db_manager, tenant_key, tied)

        try:
            everything = _payload(await _list_tasks(client, limit=30))
            all_ids = [t["task_id"] for t in everything["tasks"]]
            assert len(all_ids) == 30, f"expected all 30 rows, got {len(all_ids)}"
            assert all_ids == sorted(all_ids), (
                "rows tied on created_at came back in storage order rather than on a "
                "documented total order, so which row a limit discards is decided by the "
                f"heap rather than by a rule. got {all_ids!r}"
            )

            page = _payload(await _list_tasks(client, limit=10))
            page_ids = [t["task_id"] for t in page["tasks"]]
            assert page_ids == sorted(all_ids)[:10], (
                "the bounded page must be the deterministic prefix of that total order -- "
                f"otherwise the cut is arbitrary among the tied rows. got {page_ids!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_limit_is_capped_at_a_hard_maximum(self, mcp_client, db_manager):
        """The contract copied from ``search_memory``: a sane default AND a hard max.

        The max is the thing that makes the default safe to raise. Rejecting an
        over-max value at the boundary is what ``search_memory`` already does via
        ``Field(ge=1, le=...)``, and reusing that shape means a caller learns one rule.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(3))

        try:
            result = await _list_tasks(client, limit=EXPECTED_MAX_LIMIT + 1)
            assert result.is_error, (
                "a limit above the hard maximum must be refused at the boundary, the way "
                f"search_memory refuses one; got a successful response instead: {_content_text(result)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 3. The size backstop -- rows, never fields
# ---------------------------------------------------------------------------


class TestTheSizeBackstopDropsWholeRows:
    async def test_the_size_backstop_drops_whole_rows(self, mcp_client, db_manager):
        """The guard beneath the other three, so a bug can never dump a quarter-million tokens.

        Two things are asserted, and the second matters more than the first. The response
        must come in under the ceiling -- and every row that survives must still be a
        WHOLE row. Trimming fields to fit is the wrong shape for a list: the in-repo
        field-trimmer protects the display name and discards the identifier, which
        produces husks an agent cannot act on. A half-row is not a usable answer.

        A row count is not a size bound: ``limit`` cannot bound this on its own, because
        ``full`` mode returns ``description`` untruncated and one row is therefore
        arbitrarily large. 40 rows carrying ~4,000 characters of description each is a
        request well inside any sane row limit that is still 160,000 characters of answer.
        """
        client, tenant_key = mcp_client
        fat = [
            {
                "title": f"Fat row {i:03d} -- description-heavy task",
                "description": "x" * 4_000,
                "status": "pending",
                "age_days": i,
            }
            for i in range(40)
        ]
        await _seed(db_manager, tenant_key, fat)

        try:
            result = await _list_tasks(client, mode="full", limit=40)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)

            size = _wire_chars(payload)
            assert size <= EXPECTED_CHAR_CEILING, (
                "list_tasks has no size bound at all: mode='full' returns description "
                "untruncated, so a request well inside any row limit still returns an "
                f"unbounded answer. {size:,} chars over a {EXPECTED_CHAR_CEILING:,} ceiling. "
                f"rows returned: {len(payload['tasks'])}"
            )
            assert payload.get("truncated") is True, (
                f"a size cut must be visible on the response, got truncated={payload.get('truncated')!r}"
            )
            note = payload.get("truncation") or {}
            assert note.get("reason") == "response_size", (
                "the size cut must be distinguishable from a limit cut through the existing "
                f"reason discriminator, got {note!r}"
            )

            expected_keys = set(payload["tasks"][0])
            for row in payload["tasks"]:
                assert set(row) == expected_keys, (
                    "the backstop must drop whole ROWS, never fields off rows -- a row missing "
                    f"its identifier is a husk the caller cannot act on. got {sorted(row)!r}"
                )
                assert row.get("task_id"), f"every surviving row must keep its identifier, got {row!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_biggest_row_the_tool_can_create_still_fits(self, mcp_client, db_manager):
        """The ceiling must never answer a non-empty board with an empty page.

        A row-dropping ceiling has one degenerate failure: if a single row is larger than
        the whole budget, every row is dropped and the caller gets zero rows back for a
        board that plainly has tasks on it. Technically honest -- ``truncated`` is true
        and the advice names the remedy -- but useless.

        It is unreachable through this tool, and this test is what pins that rather than
        leaving it as a reasoned claim: ``create_task`` caps ``description`` at 20,000
        characters at the MCP boundary, so the fattest row it can produce is ~21 KB
        against a 48,000-char ceiling, and at least two of them fit. The ``description``
        COLUMN is unbounded ``Text``, so a longer row could in principle arrive from
        another write path -- the pure-function unit test covers that case and shows it
        degrades to an empty page plus an honest signal rather than to a partial row.
        """
        client, tenant_key = mcp_client
        await _seed(
            db_manager,
            tenant_key,
            [
                {"title": f"Maximum-size row {i}", "description": "z" * 20_000, "status": "pending", "age_days": i}
                for i in range(3)
            ],
        )

        try:
            payload = _payload(await _list_tasks(client, mode="full"))
            assert payload["tasks"], (
                "a board with three tasks on it must never come back as an empty page -- "
                f"got 0 rows, truncation={payload.get('truncation')!r}"
            )
            assert payload["tasks"][0]["description"], "the surviving row must be whole, description included"
            assert _wire_chars(payload) <= EXPECTED_CHAR_CEILING, (
                f"and it must still respect the ceiling: {_wire_chars(payload):,} chars"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 4. A genuinely lean row -- asserted on measured bytes
# ---------------------------------------------------------------------------


class TestTheIndexRowIsLean:
    async def test_the_index_row_is_actually_leaner_in_bytes(self, mcp_client, db_manager):
        """The claim the sibling tool makes and does not keep.

        ``mode='triage'`` on the project list is documented as the cheap projection and
        was measured as **not cheaper**. A projection is only lean if the scale says so,
        so this asserts on wire bytes rather than on the field count -- which is exactly
        the assertion that would have caught the sibling.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(30))

        try:
            index_result = await _list_tasks(client, mode="index", limit=30)
            assert not index_result.is_error, (
                "there is no lean index projection: the cheapest thing an agent can ask for "
                "today still carries the embedded task_type block on every row. "
                f"content: {_content_text(index_result)!r}"
            )
            summary_result = await _list_tasks(client, mode="summary", limit=30)
            assert not summary_result.is_error, f"content: {_content_text(summary_result)!r}"

            index_payload, summary_payload = _payload(index_result), _payload(summary_result)
            assert len(index_payload["tasks"]) == len(summary_payload["tasks"]) == 30, (
                "both projections must cover the same rows or the comparison is meaningless"
            )

            index_size = _wire_chars(index_payload["tasks"])
            summary_size = _wire_chars(summary_payload["tasks"])
            assert index_size < summary_size * 0.75, (
                "the index projection must be MEASURABLY leaner, not merely differently "
                f"shaped: {index_size:,} chars vs {summary_size:,} for the same 30 rows "
                f"({100 * (1 - index_size / summary_size):.1f}% saved)"
            )

            row = index_payload["tasks"][0]
            assert set(row) == {
                "task_id",
                "taxonomy_alias",
                "name",
                "status",
                "type",
                "due_date",
                "created_at",
            }, f"the index row is the list-and-sort row and nothing more, got {sorted(row)!r}"
            assert row["type"] == "TSK", (
                "the type must be the plain abbreviation -- the embedded block repeats a "
                f"constant and a second UUID on every row to say 'TSK'. got {row['type']!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 5. query -- search as a real verb
# ---------------------------------------------------------------------------


class TestQueryIsARealVerb:
    async def test_query_finds_a_task_by_a_word_in_its_title(self, mcp_client, db_manager):
        """ "Update the OAuth one" is how people refer to work, and it does not work today.

        There is no text search over tasks on the MCP surface at all. Same shape as
        ``search_memory``'s ``query``: case-insensitive substring, and the cheapest path
        from a vague human phrase to a single id.
        """
        client, tenant_key = mcp_client
        rows = _corpus(10)
        needle_id = str(uuid.uuid4())
        rows.append(
            {
                "id": needle_id,
                "title": "Rotate the OAuth signing key before the next release",
                "description": "Unrelated body text.",
                "status": "pending",
                "age_days": 99,
            }
        )
        await _seed(db_manager, tenant_key, rows)

        try:
            result = await _list_tasks(client, query="oauth")
            assert not result.is_error, (
                "list_tasks has no query parameter -- an agent handed 'the OAuth one' has no "
                f"way to reach it except by pulling the whole board. content: {_content_text(result)!r}"
            )
            payload = _payload(result)
            returned = [t["task_id"] for t in payload["tasks"]]
            assert returned == [needle_id], (
                f"a case-insensitive title match must return exactly the OAuth task, got {returned!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_query_containing_a_like_wildcard_is_not_treated_as_a_wildcard(self, mcp_client, db_manager):
        """``%`` and ``_`` are user text, not operators. Unescaped they silently widen the search.

        This is the failure this tool is being bounded to prevent, arriving through the
        feature meant to narrow it: a caller searching for a task about ``100%`` or a
        file named ``some_thing`` would match the entire board and get back a "search
        result" that is really the whole corpus -- looking narrow while being maximally
        wide. ``_`` is the nastier of the two, because a single-character wildcard reads
        like an ordinary word character and would not look wrong in the result.

        **Which assertion actually discriminates, verified by removing the escaping and
        re-running:** the bare ``%`` one, which goes from 1 row to all 10. The ``100%``
        and ``some_thing`` cases pass either way on this fixture -- with the escaping
        removed they become ``%100%%`` and ``%some_thing%``, which still happen to match
        only their intended row here. They are kept as documentation of the intent, but
        the bare-``%`` case is the one holding the invariant, and a future edit to this
        fixture must keep it.
        """
        client, tenant_key = mcp_client
        percent_id, underscore_id = str(uuid.uuid4()), str(uuid.uuid4())
        rows = _corpus(8)
        rows.append(
            {
                "id": percent_id,
                "title": "Cache hit rate reached 100% on the staging box",
                "description": "Unrelated body.",
                "status": "pending",
                "age_days": 97,
            }
        )
        rows.append(
            {
                "id": underscore_id,
                "title": "Rename the legacy some_thing helper",
                "description": "Unrelated body.",
                "status": "pending",
                "age_days": 96,
            }
        )
        await _seed(db_manager, tenant_key, rows)

        try:
            percent = _payload(await _list_tasks(client, query="100%"))
            returned = [t["task_id"] for t in percent["tasks"]]
            assert returned == [percent_id], (
                "'100%' must match the one task that literally contains it -- an unescaped "
                f"'%' makes it a wildcard that returns the whole board. got {len(returned)} rows: {returned!r}"
            )

            # 'some_thing' must NOT match 'someXthing'; the underscore is a literal.
            underscore = _payload(await _list_tasks(client, query="some_thing"))
            assert [t["task_id"] for t in underscore["tasks"]] == [underscore_id], (
                "'some_thing' must match literally -- an unescaped '_' is a single-character "
                f"wildcard. got {[t['task_id'] for t in underscore['tasks']]!r}"
            )

            # And the negative direction: a bare '%' finds nothing, because no task
            # contains a literal percent sign except the one above.
            bare = _payload(await _list_tasks(client, query="%"))
            assert [t["task_id"] for t in bare["tasks"]] == [percent_id], (
                "a bare '%' must be searched for as a character, not expanded to match every "
                f"row. got {len(bare['tasks'])} of {len(rows)} rows"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_query_also_matches_the_description(self, mcp_client, db_manager):
        """The word a user remembers is often in the body, not the title."""
        client, tenant_key = mcp_client
        rows = _corpus(10)
        needle_id = str(uuid.uuid4())
        rows.append(
            {
                "id": needle_id,
                "title": "Unremarkable title",
                "description": "The retry backoff on the webhook consumer needs a jitter term.",
                "status": "pending",
                "age_days": 98,
            }
        )
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_tasks(client, query="JITTER"))
            returned = [t["task_id"] for t in payload["tasks"]]
            assert returned == [needle_id], f"a description match must be found case-insensitively, got {returned!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# BOTH-SIDES GUARDS -- these pass on master AND after the change.
# If one of these goes red, the instrument is broken and every RED above is void.
# ---------------------------------------------------------------------------


class TestNothingThatWorksTodayStopsWorking:
    async def test_an_unbounded_small_list_is_returned_whole(self, mcp_client, db_manager):
        """BOTH-SIDES GUARD. The overwhelmingly common call must be untouched.

        A board under the default is the normal case; it comes back complete, in the same
        order, before and after. This is what proves the RED above is about the bound and
        not about the harness being unable to list tasks at all.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(12))

        try:
            result = await _list_tasks(client)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload["count"] == 12, f"a small board comes back whole, got {payload['count']}"
            assert len(payload["tasks"]) == 12
            created = [t["created_at"] for t in payload["tasks"]]
            assert created == sorted(created, reverse=True), f"newest-created first, unchanged, got {created!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_shipped_response_keys_are_unchanged(self, mcp_client, db_manager):
        """BOTH-SIDES GUARD. Every new key is ADDITIVE; no existing key moves or changes type.

        Backward compatibility is absolute here: no change whose effect is "calls that
        succeed today now fail".
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(4))

        try:
            payload = _payload(await _list_tasks(client))
            for key in ("tasks", "count", "mode", "tenant_key", "product_id"):
                assert key in payload, f"the shipped key {key!r} must survive; got {sorted(payload)!r}"
            assert isinstance(payload["tasks"], list)
            assert isinstance(payload["count"], int)
            assert payload["mode"] == "summary"

            row = payload["tasks"][0]
            for key in (
                "task_id",
                "title",
                "status",
                "priority",
                "task_type",
                "taxonomy_alias",
                "series_number",
                "subseries",
                "hidden",
                "due_date",
                "created_at",
            ):
                assert key in row, f"the shipped summary row key {key!r} must survive; got {sorted(row)!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_full_mode_still_carries_the_description(self, mcp_client, db_manager):
        """BOTH-SIDES GUARD. ``full`` mode is the deep read and stays deep.

        The lean row is a NEW third option, not a quiet downgrade of an existing one --
        a caller that asks for ``full`` today and gets a thinner row tomorrow is exactly
        the silent behaviour change this suite exists to prevent.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(4))

        try:
            payload = _payload(await _list_tasks(client, mode="full"))
            row = payload["tasks"][0]
            assert "description" in row, f"full mode must still carry description, got {sorted(row)!r}"
            assert row["description"], "the description must not come back empty"
            assert payload["mode"] == "full"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_memory_limit_still_truncates_the_description(self, mcp_client, db_manager):
        """BOTH-SIDES GUARD. The one size control that already exists keeps working."""
        client, tenant_key = mcp_client
        await _seed(
            db_manager,
            tenant_key,
            [{"title": "Long body", "description": "y" * 500, "status": "pending"}],
        )

        try:
            payload = _payload(await _list_tasks(client, mode="full", memory_limit=50))
            description = payload["tasks"][0]["description"]
            assert description.endswith("..."), f"memory_limit must still truncate, got {description[:80]!r}"
            assert len(description) == 53, f"50 chars plus the ellipsis, got {len(description)}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)
