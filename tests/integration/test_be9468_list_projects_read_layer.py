# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9468 -- the agent-facing project list cannot tell the caller how big the answer is.

The operator's framing: *"I am not sure why the tool is pulling entire lists of all
projects unless the user specifically asks to do so. But the user SHOULD have the choice
of doing this. Ultimately I want a listing and searching tool."*

Root cause: **nothing tells the caller how big an answer will be before it asks for it.**
An agent asked "what did we ship" cannot know whether that is 5 rows or 5,000, so it asks
for everything and hopes. A size ceiling truncates the guess; it does not improve it.

Four defects, each asserted below at the MCP boundary:

1. **``mode="triage"`` is advertised as the cheap projection and is byte-identical to the
   default.** ``_MODE_TO_PROJECTION["triage"]`` is ``(0, False, None)``, and the mode
   branch sets ``summary_only=False`` before ``effective_depth = 0 if summary_only else
   depth`` resolves back to 0 -- the same depth the default already produces. The shipped
   tool docstring says *"triage = id+name+status+dates (cheapest)"*. A projection that is
   documented lean and is not is a dishonest signal, which is the class this whole family
   of fixes exists to kill.
2. **No response says how much exists.** The caller sees the rows it got and nothing about
   the board they came from, so it cannot choose a narrower next question.
3. **There is no ``limit``.** Asking for less was not expressible; the row ceiling is a
   defensive cap, not a caller-facing choice.
4. **There is no text search.** ``search`` has existed at the repository layer since
   BE-6076 (``_build_list_conditions``, a case-insensitive ``ilike`` across name / id /
   taxonomy_alias) and ``ProjectService.list_projects`` already forwards it -- the MCP
   boundary simply never passed it.

FAIL-FIRST, measured on base master ``048e65df6`` (unpatched). Every test in
``TestTheCheapProjectionIsActuallyCheap``, ``TestTheAnswerTeachesTheShapeOfTheNextQuestion``,
``TestAskingForLessIsPossible`` and ``TestSearchIsARealVerb`` fails there.

``TestTheHarnessItself`` is the BOTH-SIDES GUARD and the proof the red above is the
assertion failing rather than a broken instrument: it exercises the identical transport,
fixture and seed, and must pass BEFORE and AFTER the change. If it ever goes red, nothing
else in this module proves anything.

``TestTheRowCeilingCannotBoundARicherProjection`` is a CHARACTERIZATION test: it passes on
master too, because it measures a property of the shipped code rather than a fix. It pins
the finding that ``_MCP_LIST_PROJECT_CEILING`` is a row cap over an arbitrarily large row,
so it cannot bound a ``depth >= 1`` response at all.

Measurement discipline: bytes are taken on the REAL MCP wire serializer,
``pydantic_core.to_json(data, fallback=str).decode()`` (compact JSON, reached via
``fastmcp/tools/base.py`` ``_convert_to_content``), and tokens with a real BPE tokenizer.
**The house ``chars // 4`` convention is deliberately NOT used**: measured on this payload
shape it understates by 23-36%, because identifiers tokenize worst (a UUID is 38 chars but
23 tokens; an ISO timestamp 32 chars but 19). Asserting leanness on measured bytes is the
point -- a claim of cheapness checked by reading the code is what shipped defect 1.

Transport: the REAL ``@mcp.tool`` path via ``create_connected_server_and_client_session``
against the real Postgres test DB -- the boundary the operator's client actually hits.

Parallel-safe: every test generates a fresh ``tenant_key`` and purges its own rows in a
``finally``; these MCP-adapter calls commit for real via ``db_manager``, so there is no
rollback isolation to lean on. No module-level mutable state, no ordering dependencies.

Edition Scope: Both.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from pydantic_core import to_json

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import _mcp_adapter_query_mixin as ceiling_mod
from giljo_mcp.services.project_service import _mcp_list_bounds as bounds_mod
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Measurement helpers -- the real wire format, and a real tokenizer.
# ---------------------------------------------------------------------------


def _wire_bytes(obj) -> int:
    """Serialized length on the REAL MCP wire serializer.

    ``pydantic_core.to_json(..., fallback=str)`` is what FastMCP uses to turn a tool
    result into content (compact JSON -- ``{"a":1,"b":"x"}``, no spaces). Measuring with
    ``json.dumps`` instead inflates every row by its separator whitespace and is not the
    payload the caller is charged for.
    """
    return len(to_json(obj, fallback=str).decode())


def _tokens(obj) -> int:
    """Token count of the serialized object under a real BPE tokenizer.

    ``tiktoken`` is not Claude's tokenizer, so the ABSOLUTE number is corroboration
    rather than certification. What it is used for here is a RATIO and a COMPARISON
    between two payloads measured the same way, both of which are robust across BPE
    tokenizers. It is a declared production dependency (``requirements.txt``), not a
    test-only import.
    """
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(to_json(obj, fallback=str).decode()))


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


# ---------------------------------------------------------------------------
# Fixtures -- the real transport over the real database.
# ---------------------------------------------------------------------------


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


def _iso(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T12:00:00+00:00")


async def _seed(db_manager, tenant_key: str, rows: list[dict]) -> str:
    """Commit one active product plus the given project rows. Returns the product id.

    Each row carries ``id``, ``name``, ``created``, ``completed`` (``YYYY-MM-DD`` or
    None), ``status`` and optionally ``description`` / ``mission``. ``series_number`` is
    assigned sequentially so the ``uq_project_taxonomy_active`` NULLS-NOT-DISTINCT index
    cannot collide.
    """
    product_id = str(uuid.uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9468 Product {uuid.uuid4().hex[:6]}",
                description="BE-9468 -- the read layer on the agent-facing project list.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        for index, row in enumerate(rows, start=1):
            session.add(
                Project(
                    id=row["id"],
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name=row["name"],
                    description=row.get("description", "Seeded for the read-layer reproduction."),
                    mission=row.get("mission", "Prove the answer teaches the shape of the next question."),
                    status=row["status"],
                    staging_status="staging_complete",
                    series_number=index,
                    created_at=_iso(row["created"]),
                    completed_at=_iso(row["completed"]) if row.get("completed") else None,
                )
            )
        await session.commit()

    return product_id


def _row(name: str, status: str, created: str, completed: str | None = None, **extra) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "status": status,
        "created": created,
        "completed": completed,
        **extra,
    }


def _mixed_board() -> list[dict]:
    """A board shaped like the operator's: completions dominate, unfinished work is small.

    *"users rarely have thousands of INACTIVE projects, but often thousands of COMPLETED
    ones"* -- so the expensive query is the archive read and the useful query is narrow.
    Eight completed, two unfinished, at the same proportion, small enough to run in
    milliseconds.
    """
    completed = [
        _row(f"OAuth token refresh pass {n}", "completed", f"2026-0{n}-01", f"2026-0{n}-15") for n in range(1, 9)
    ]
    unfinished = [
        _row("Billing webhook retry", "inactive", "2026-07-01"),
        _row("Roadmap ordering polish", "inactive", "2026-07-02"),
    ]
    return completed + unfinished


async def _list_projects(client, **kwargs) -> object:
    """Invoke the agent-facing ``list_projects`` @mcp.tool over the real transport."""
    async with client() as mcp_session:
        return await mcp_session.call_tool("list_projects", kwargs)


# ---------------------------------------------------------------------------
# BOTH-SIDES GUARD. Must pass before AND after. Read this first when anything is red.
# ---------------------------------------------------------------------------


class TestTheHarnessItself:
    """If any of these is red, every failure below is an instrument fault, not a finding.

    A broken instrument that goes red is not a reproduction. These assert only behavior
    that BE-9468 does not change: the seeded rows come back, the count matches, and the
    shipped BE-9455 Symptom A truncation signal is intact.
    """

    async def test_the_default_list_returns_every_unfinished_seeded_row(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        rows = _mixed_board()
        await _seed(db_manager, tenant_key, rows)
        try:
            result = await _list_projects(client)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            names = {p["name"] for p in payload["projects"]}
            assert names == {"Billing webhook retry", "Roadmap ordering polish"}, (
                f"the default list is active-lifecycle only; got {sorted(names)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_untruncated_response_still_reports_truncated_false(self, mcp_client, db_manager):
        """BE-9455 Symptom A's shipped signal is untouched by this change."""
        client, tenant_key = mcp_client
        rows = _mixed_board()
        await _seed(db_manager, tenant_key, rows)
        try:
            payload = _payload(await _list_projects(client, include_completed=True))
            assert payload["count"] == len(rows), f"all seeded rows should be present, got {payload['count']}"
            assert payload.get("truncated") is False, (
                f"a complete list must report truncated=False, got {payload.get('truncated')!r}"
            )
            assert "truncation" not in payload, (
                f"a complete list must carry no truncation detail block, got {payload.get('truncation')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_measurement_helpers_agree_with_the_transport(self, mcp_client, db_manager):
        """The measuring instrument itself, checked against a payload of known shape.

        Guards the two ways the byte measurements below could silently lie: measuring a
        different serializer than the wire uses, and a tokenizer that returns something
        unrelated to the text. Compact JSON has no ``", "`` separator; a tokenizer that
        works produces fewer tokens than characters and more than zero.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client, include_completed=True))
            wire = to_json(payload["projects"], fallback=str).decode()
            assert '", "' not in wire, "the wire serializer must emit COMPACT json -- this is not the wire format"
            assert 0 < _tokens(payload["projects"]) < _wire_bytes(payload["projects"]), (
                "the tokenizer must return a positive count below the character count"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# DEFECT 1 -- the cheap projection is not cheap.
# ---------------------------------------------------------------------------


class TestTheCheapProjectionIsActuallyCheap:
    async def test_triage_is_leaner_than_the_default_projection(self, mcp_client, db_manager):
        """THE regression for the stated defect, asserted on MEASURED BYTES.

        ``mode="triage"`` is advertised in the shipped tool docstring as
        *"id+name+status+dates (cheapest)"*. On master it resolves to the same depth 0 the
        ``summary_only=True`` default already produces, so it is byte-identical -- there is
        no cheap projection on this tool at all, only one that says it is.

        Asserted on bytes rather than on field names deliberately: the defect is a claim
        about cost, so the test has to be about cost. A field-name assertion would pass on
        a projection that dropped a cheap field and kept an expensive one.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            default_rows = _payload(await _list_projects(client, include_completed=True))["projects"]
            triage_rows = _payload(await _list_projects(client, include_completed=True, mode="triage"))["projects"]

            assert len(triage_rows) == len(default_rows), (
                "the comparison is only meaningful over the same row set; "
                f"default returned {len(default_rows)}, triage {len(triage_rows)}"
            )
            default_bytes = _wire_bytes(default_rows)
            triage_bytes = _wire_bytes(triage_rows)
            assert triage_bytes < default_bytes, (
                "mode='triage' is documented as the CHEAPEST projection but costs "
                f"{triage_bytes} wire bytes against the default's {default_bytes} "
                f"({triage_bytes / len(triage_rows):.1f} vs {default_bytes / len(default_rows):.1f} B/row). "
                "A projection that is documented lean and is not is a dishonest signal. "
                f"triage row keys: {sorted(triage_rows[0])!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_triage_row_carries_exactly_the_index_fields(self, mcp_client, db_manager):
        """An index row is what sorting and identifying need, and nothing more.

        ``project_id`` is non-negotiable -- it is the only field an agent can ACT on, and a
        row without it is a label, not an answer. The dates are what any ordering question
        needs. Everything else is enrichment that belongs to a richer mode.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            triage_rows = _payload(await _list_projects(client, include_completed=True, mode="triage"))["projects"]
            keys = set(triage_rows[0])
            required = {"project_id", "taxonomy_alias", "name", "status", "project_type", "created_at", "completed_at"}
            assert required <= keys, f"the index row is missing {sorted(required - keys)!r}; got {sorted(keys)!r}"
            forbidden = {"description", "mission", "agent_summary", "memory_entries", "agent_details"}
            assert not (forbidden & keys), f"the index row must carry no enrichment; found {sorted(forbidden & keys)!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# DEFECT 2 -- no response says how much exists.
# ---------------------------------------------------------------------------


class TestTheAnswerTeachesTheShapeOfTheNextQuestion:
    async def test_every_response_carries_a_counts_block(self, mcp_client, db_manager):
        """THE KEYSTONE. Without it, every other rule is the model guessing.

        An agent that knows *"8 completed, 2 inactive"* before it chooses can ask a narrow
        question. An agent that does not has exactly one strategy available -- ask for
        everything and hope -- which is the behavior the operator reported.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client))
            counts = payload.get("counts")
            assert isinstance(counts, dict), f"every list response must carry a counts block, got {counts!r}"
            assert counts.get("by_status", {}).get("completed") == 8, (
                f"the counts must report the archive the caller did NOT ask for, got {counts!r}"
            )
            assert counts.get("by_status", {}).get("inactive") == 2, f"got {counts!r}"
            assert counts.get("total") == 10, f"the counts must report the whole board total, got {counts!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_counts_describe_the_whole_board_not_the_filtered_page(self, mcp_client, db_manager):
        """The load-bearing design call, pinned as a test.

        The default list is active-lifecycle only, so a counts block scoped to what was
        returned would report *"inactive: 2"* and never mention the eight completed
        projects -- it would be derivable from the rows themselves and therefore carry no
        information at all. The operator's stated need is to know the archive is there
        BEFORE asking for it, which only a whole-board count can answer.

        ``returned`` is carried alongside so the relationship between the page and the
        board is explicit rather than inferred.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client))
            counts = payload.get("counts") or {}
            assert payload["count"] == 2, f"the default page is active-lifecycle only, got {payload['count']}"
            assert counts.get("total") == 10, (
                "the counts must describe the whole board, not the two rows returned -- "
                f"a page-scoped count is derivable from the page and tells the caller nothing new. got {counts!r}"
            )
            assert counts.get("returned") == 2, f"the counts must state how many rows this page carried, got {counts!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_by_type_is_populated_from_a_real_taxonomy_join(self, mcp_client, db_manager):
        """`by_type` must come back with real abbreviations, not silently always empty.

        The counts query reaches the abbreviation through an OUTER JOIN from
        ``Project.project_type_id`` to ``TaxonomyType.id``, and rows with no type
        contribute a NULL that is skipped. **So a wrong join condition would not raise --
        it would produce an empty ``by_type`` on every call, forever.** That is a
        dishonest signal of exactly the kind this project exists to remove: a documented
        key that is always empty looks like "this tenant has no types" rather than "this
        query is broken". The other counts tests seed untyped projects and would all pass
        against that bug, which is precisely why this test exists.
        """
        from giljo_mcp.models.projects import TaxonomyType

        client, tenant_key = mcp_client
        rows = _mixed_board()
        await _seed(db_manager, tenant_key, rows)
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            be_type = TaxonomyType(id=str(uuid.uuid4()), tenant_key=tenant_key, abbreviation="BE", label="Backend")
            session.add(be_type)
            await session.flush()
            for row in rows[:3]:
                project = await session.get(Project, row["id"])
                project.project_type_id = be_type.id
            await session.commit()

        try:
            counts = _payload(await _list_projects(client))["counts"]
            assert counts["by_type"] == {"BE": 3}, (
                "by_type must carry the real taxonomy abbreviation for typed projects; "
                f"an empty map here means the join is wrong, not that the board is untyped. got {counts!r}"
            )
            assert counts["total"] == 10, f"untyped projects must still be counted in the board total, got {counts!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_counts_block_is_small(self, mcp_client, db_manager):
        """A block that teaches the next question must not itself be the expensive answer.

        Budgeted at roughly 200 tokens. It is bounded by construction -- one entry per
        status (six), one per configured taxonomy type, and four timestamps -- so this
        asserts the construction held rather than a number that happens to fit today.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            counts = _payload(await _list_projects(client)).get("counts")
            # Assert presence FIRST. Without this the budget assertion passes vacuously on
            # a missing block -- ``to_json(None)`` is four characters, so "absent" would
            # score as "comfortably within budget". A test that goes green on the feature
            # being absent is the same dishonest signal this module exists to remove.
            assert isinstance(counts, dict), f"there is no counts block to measure, got {counts!r}"
            cost = _tokens(counts)
            assert cost <= 200, f"the counts block costs {cost} tokens against a ~200 budget: {counts!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# DEFECT 3 -- asking for less was not expressible.
# ---------------------------------------------------------------------------


class TestAskingForLessIsPossible:
    async def test_a_limit_bounds_the_rows_returned(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            result = await _list_projects(client, include_completed=True, limit=3)
            assert not result.is_error, f"limit must be an accepted parameter. content: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload["count"] == 3, f"limit=3 must return 3 rows, got {payload['count']}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_limited_response_says_so_through_the_shipped_signal(self, mcp_client, db_manager):
        """Extend the BE-9455 vocabulary; never fork it.

        ``truncated: bool`` always present, a ``truncation`` block only on a cut, with the
        shipped ``{reason, ceiling, rows_fetched, dropped, advice}`` keys. ``reason`` is the
        discriminator, so a limit cut and a defensive-ceiling cut are distinguishable by a
        caller that already understands the shipped shape. A second vocabulary would make
        the tool behave two contradictory ways depending on which bound happened to bind.

        BE-9469 WIDENED THE ALLOWED SET BY EXACTLY ONE KEY, and kept the lock's teeth. The
        assertion was ``set(note) == SHIPPED``, which is a stronger claim than the docstring
        it enforces: it forbade the additive extension this block was designed for, which is
        how ``next_cursor`` came to live INSIDE ``truncation`` rather than beside it. So the
        lock is now two-sided instead of relaxed -- every shipped key must still be present
        (nothing may be dropped), and nothing outside a NAMED extension set may appear (no
        key arrives unannounced). Adding a second key still fails this test, which is the
        property worth keeping.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client, include_completed=True, limit=3))
            assert payload.get("truncated") is True, (
                f"a response cut by limit must say so; got truncated={payload.get('truncated')!r}"
            )
            note = payload.get("truncation")
            assert isinstance(note, dict), f"a cut response must carry the shipped detail block, got {note!r}"
            assert note.get("reason") == "limit", (
                f"reason is the discriminator between the bounds that can cut; got {note!r}"
            )
            assert note.get("ceiling") == 3, f"the detail must name the bound that cut, got {note!r}"
            assert note.get("rows_fetched") == 3, f"the detail must state how many rows survived, got {note!r}"
            shipped = {"reason", "ceiling", "rows_fetched", "dropped", "advice"}
            # BE-9469: the ONE deliberate extension. Named here, so a third key is a failure.
            allowed_extensions = {"next_cursor"}
            assert shipped <= set(note), (
                f"the truncation block dropped a SHIPPED key -- a caller reading the old shape "
                f"would break: missing {sorted(shipped - set(note))!r}"
            )
            assert set(note) <= shipped | allowed_extensions, (
                f"the truncation block grew an unannounced key; extend the vocabulary "
                f"deliberately or not at all. unexpected: {sorted(set(note) - shipped - allowed_extensions)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_limit_that_does_not_bind_leaves_the_response_untruncated(self, mcp_client, db_manager):
        """The other direction: a limit above the match count is not a cut and must not claim one."""
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client, include_completed=True, limit=50))
            assert payload["count"] == 10, f"a non-binding limit must return every row, got {payload['count']}"
            assert payload.get("truncated") is False, f"got truncated={payload.get('truncated')!r}"
            assert "truncation" not in payload, f"got {payload.get('truncation')!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_cut_is_deterministic_when_timestamps_tie(self, mcp_client, db_manager):
        """A sort that decides what to DISCARD has to be a total order.

        ``created_at`` defaults to ``func.now()``, and PostgreSQL's ``now()`` is
        transaction-scoped -- so every project inserted in one transaction carries a
        byte-identical timestamp. Ordered by that column alone those rows have NO defined
        order, and the database is free to return them differently between two calls.

        That was harmless while the list was unbounded: every tied row came back either
        way. **``limit`` is what makes tie-order decide WHICH row is thrown away.** So the
        unique ``id`` tiebreak already present in both of this surface's orderings
        (``_completion_recency_order_clauses`` and the repository's ``created_at``
        fallback, both ending ``Project.id.asc()``) acquires a second, load-bearing job
        under BE-9468 that it did not have when BE-9455 added it.

        This asserts the discriminating property rather than mere repeatability: the page
        must be the ``id``-ascending prefix of the tied set. A "two calls agree" assertion
        would pass without any tiebreak at all, because at this scale Postgres returns
        stable heap order -- it would look like a guard and guard nothing. The seeded ids
        are random UUIDs, so insertion order is uncorrelated with id order and heap order
        cannot satisfy this by luck.
        """
        client, tenant_key = mcp_client
        # One timestamp, one transaction -- the real tie, not a simulated one.
        tied = [_row(f"tied project {n}", "inactive", "2026-07-04") for n in range(8)]
        await _seed(db_manager, tenant_key, tied)
        try:
            expected = sorted(r["id"] for r in tied)[:3]
            payload = _payload(await _list_projects(client, limit=3))
            returned = [p["project_id"] for p in payload["projects"]]

            assert returned == expected, (
                "with every created_at identical, the kept rows must be the id-ascending "
                "prefix -- otherwise which project the limit discards is undefined and can "
                f"differ between two identical calls.\n  expected {expected}\n  got      {returned}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_limit_cut_falls_on_the_oldest_completions(self, mcp_client, db_manager):
        """BE-9455 Symptom A's ordering is load-bearing and the limit must not disturb it.

        ``completed_at DESC NULLS FIRST`` makes unfinished work un-droppable, so a cut can
        only ever fall on the oldest completions -- the one bucket where "older" honestly
        means "less wanted". A limit that re-sorted, or that sliced before that ordering
        was applied, would resurrect the exact defect BE-9455 fixed. Museum rule: this
        pins the existing behavior rather than reasoning about it.
        """
        client, tenant_key = mcp_client
        rows = _mixed_board()
        await _seed(db_manager, tenant_key, rows)
        try:
            payload = _payload(await _list_projects(client, include_completed=True, limit=3))
            returned = {p["name"] for p in payload["projects"]}
            assert "Billing webhook retry" in returned, (
                f"unfinished work must survive any cut; got {sorted(returned)!r}"
            )
            assert "Roadmap ordering polish" in returned, f"got {sorted(returned)!r}"
            assert "OAuth token refresh pass 1" not in returned, (
                f"the OLDEST completion is what a cut should discard; got {sorted(returned)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# DEFECT 4 -- search is not a verb on this surface.
# ---------------------------------------------------------------------------


class TestTheResponseSizeBackstop:
    """The bound a ROW cap cannot be, on the one tool where all three are reachable.

    ``limit`` bounds rows; at ``depth >= 1`` one row is arbitrarily large. Measured, a
    single ``mode='planning'`` row with a 9,000-char description is ~1,976 tokens, so
    ``limit=500`` -- a value this tool now advertises as legitimate -- can reach roughly
    a million tokens. A row cap and a size cap are not alternatives.

    The ceiling is patched small rather than seeded past, for the same reason BE-9455's
    suite patches its ceiling to 4: the constant IS the mechanism, so a small dataset
    against a small ceiling exercises the identical code path deterministically and in
    milliseconds, and proves the ceiling VALUE is not what makes the behaviour correct.
    """

    async def test_a_size_cut_reports_response_size_and_says_a_bigger_limit_will_not_help(
        self, mcp_client, db_manager, monkeypatch
    ):
        """The discriminator earns its keep only if each reason names a remedy that works.

        A ``limit`` cut is recoverable by raising ``limit``. A size cut is NOT -- the same
        payload comes back. Telling the caller to raise the limit here would be a helpful
        voice attached to advice that cannot work, which is the silent-wrong-signal defect
        wearing a disguise.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(bounds_mod, "MCP_LIST_CHAR_CEILING", 3000)
        rows = [
            _row(f"verbose project {n}", "inactive", "2026-07-03", description="x" * 2000, mission="y" * 500)
            for n in range(6)
        ]
        await _seed(db_manager, tenant_key, rows)
        try:
            payload = _payload(await _list_projects(client, mode="planning"))
            assert payload["truncated"] is True, f"a size-cut response must say so; got {payload.get('truncated')!r}"
            note = payload["truncation"]
            assert note["reason"] == "response_size", (
                f"a cut made by response size must name that bound, not the row limit; got {note!r}"
            )
            assert note["ceiling"] == 3000, f"the detail must name the bound that cut, got {note!r}"
            assert "HIGHER LIMIT WILL NOT RETURN MORE" in note["advice"], (
                f"the advice must not send the caller to a remedy that cannot work; got {note['advice']!r}"
            )
            assert set(note) == {"reason", "ceiling", "rows_fetched", "dropped", "advice"}, (
                f"the shipped five-key shape must be reused, got {sorted(note)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_ceiling_holds_as_a_postcondition_on_the_payload_the_client_receives(
        self, mcp_client, db_manager, monkeypatch
    ):
        """Asserted on the FINAL payload, `_meta` and truncation block included.

        The in-repo field trimmer writes its truncation metadata AFTER its last size
        check and overshoots its own ceiling by exactly 64 chars while reporting success.
        **A bound that does not hold is worse than no bound, because it reports success.**
        So this measures what the client actually receives, not what the fitter thought
        it was returning -- across several ceilings, because a postcondition that holds
        at one value and not another is not a postcondition.

        **The rows are deliberately SMALL, and that is what makes this a guard.** With
        fat rows the fitter stops far below the budget and the leftover slack silently
        absorbs any overshoot -- an earlier version of this test used 1,500-char
        descriptions and **passed with the truncation block uncharged AND the transport
        allowance set to zero**, i.e. it would have certified both of the bugs it exists
        to catch. Small rows pack the budget tight, so the slack after the last row that
        fits is smaller than the block being forgotten, and the breach becomes visible.
        Verified in both directions before being trusted.
        """
        client, tenant_key = mcp_client
        rows = [_row(f"p{n}", "inactive", "2026-07-03") for n in range(40)]
        await _seed(db_manager, tenant_key, rows)
        try:
            for ceiling in (1200, 1650, 2100, 2600):
                monkeypatch.setattr(bounds_mod, "MCP_LIST_CHAR_CEILING", ceiling)
                result = await _list_projects(client, limit=500)
                assert not result.is_error, f"ceiling {ceiling}: {_content_text(result)!r}"
                payload = _payload(result)
                actual = _wire_bytes(payload)
                assert actual <= ceiling, (
                    f"the ceiling must HOLD on the delivered payload, not approximately: "
                    f"{actual} chars against a {ceiling} ceiling, {payload['count']} rows returned"
                )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_single_oversized_row_yields_an_empty_page_whose_advertised_remedy_works(
        self, mcp_client, db_manager
    ):
        """The degenerate case, at the REAL ceiling -- and it is reachable here.

        ``mission`` is capped at 100,000 chars at the MCP boundary (``MCP_MISSION_MAX``)
        and is serialized in full at ``depth >= 1``, so **one project row can exceed the
        48,000-char ceiling on its own.** The sibling task tool cannot reach this -- its
        description cap is 20,000, so its fattest row is ~21 KB and at least two always fit
        -- but this tool can, and a bound that returns an empty page on a non-empty board is
        alarming unless the response says what to do instead.

        Dropping every row is the CORRECT behaviour: the alternative is returning a row
        that breaches the ceiling, which un-does the postcondition the whole backstop
        exists to provide. What makes it acceptable is that the advice names a remedy
        that actually works -- so this asserts the remedy, not just the message. A
        ``mode='triage'`` row is ~250 chars and always fits.

        Run at the SHIPPED ceiling deliberately, unpatched: the point is that this is
        reachable in production, not that a small ceiling can be provoked.
        """
        client, tenant_key = mcp_client
        fat = _row("one enormous mission", "inactive", "2026-07-03", description="d" * 20_000, mission="m" * 90_000)
        await _seed(db_manager, tenant_key, [fat, *_mixed_board()])
        try:
            planning = _payload(await _list_projects(client, mode="planning"))
            assert planning["count"] == 0, (
                "a row larger than the whole ceiling cannot be returned without breaching "
                f"it; the honest answer is an empty page. got {planning['count']} rows"
            )
            assert planning["truncated"] is True, "an empty page on a non-empty board must say it was cut"
            assert planning["truncation"]["reason"] == "response_size", f"got {planning['truncation']!r}"
            assert "mode='triage'" in planning["truncation"]["advice"], (
                f"the advice must name the remedy that works; got {planning['truncation']['advice']!r}"
            )
            assert planning["counts"]["total"] == 11, (
                "the counts block must still report the whole board -- it is the ONLY thing "
                f"telling the caller the page is empty by size and not by emptiness. got {planning['counts']!r}"
            )

            # THE REMEDY, exercised rather than asserted.
            triage = _payload(await _list_projects(client, mode="triage"))
            assert triage["count"] == 3, (
                "the advertised remedy must actually work: the lean row must return the "
                f"active-lifecycle rows the rich one could not. got {triage['count']}"
            )
            assert triage["truncated"] is False, f"the lean row fits comfortably; got {triage!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_response_under_the_ceiling_is_not_reported_as_size_cut(self, mcp_client, db_manager):
        """BOTH-SIDES GUARD on the new bound: it must not claim a cut it did not make."""
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client, include_completed=True, limit=50))
            assert payload["truncated"] is False, f"got {payload.get('truncated')!r}"
            assert "truncation" not in payload, f"got {payload.get('truncation')!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTheThreeWayPrecedence:
    """`defensive_ceiling` > `response_size` > `limit`. Only this tool can reach all three.

    Exactly one ``reason`` may be reported, and the winner is the bound whose obvious
    remedy does NOT work. Reporting a recoverable reason while an unrecoverable one is
    also true sends the caller somewhere that cannot help.
    """

    async def test_size_beats_limit_when_both_bind(self, mcp_client, db_manager, monkeypatch):
        """Raising `limit` would return the identical payload, so `limit` must not be blamed."""
        client, tenant_key = mcp_client
        monkeypatch.setattr(bounds_mod, "MCP_LIST_CHAR_CEILING", 3000)
        rows = [
            _row(f"verbose project {n}", "inactive", "2026-07-03", description="x" * 2000, mission="y" * 500)
            for n in range(8)
        ]
        await _seed(db_manager, tenant_key, rows)
        try:
            # limit=5 of 8 rows binds, AND the payload blows the 3000-char ceiling.
            payload = _payload(await _list_projects(client, mode="planning", limit=5))
            assert payload["truncated"] is True
            assert payload["truncation"]["reason"] == "response_size", (
                "when the size bound and the limit both bit, size wins -- a bigger limit "
                f"returns the same payload. got {payload['truncation']!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_defensive_ceiling_beats_both(self, mcp_client, db_manager, monkeypatch):
        """THE top of the order, and the case only this tool can reach.

        A defensive-ceiling cut means the underlying set was truncated before projection,
        so NO parameter the caller can change yields a complete answer -- not a bigger
        limit, not a leaner row. It has to win the ``reason`` even when the other two
        bounds also bit, or the caller is told to try something that cannot work.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        monkeypatch.setattr(bounds_mod, "MCP_LIST_CHAR_CEILING", 3000)
        rows = [
            _row(f"verbose project {n}", "inactive", "2026-07-03", description="x" * 2000, mission="y" * 500)
            for n in range(8)
        ]
        await _seed(db_manager, tenant_key, rows)
        try:
            payload = _payload(await _list_projects(client, mode="planning", limit=2))
            assert payload["truncated"] is True
            note = payload["truncation"]
            assert note["reason"] == "defensive_ceiling", (
                "the defensive ceiling outranks both other bounds -- it is the only one "
                f"whose remedy is not available to the caller. got {note!r}"
            )
            assert note["ceiling"] == 4, f"the detail must name the ceiling that cut, got {note!r}"
            assert "raising limit will NOT complete it" in note["advice"], f"got {note['advice']!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestSearchIsARealVerb:
    async def test_query_narrows_the_list_by_name(self, mcp_client, db_manager):
        """*"update the OAuth one"* -- the cheapest path from a vague prompt to a single id.

        The matcher itself is not new: BE-6076 shipped a case-insensitive substring across
        name / id / taxonomy_alias in ``_build_list_conditions``, and
        ``ProjectService.list_projects`` already forwards ``search``. The MCP boundary
        simply never passed it, so the capability existed and was unreachable by an agent.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            result = await _list_projects(client, include_completed=True, query="oauth")
            assert not result.is_error, f"query must be an accepted parameter. content: {_content_text(result)!r}"
            payload = _payload(result)
            names = {p["name"] for p in payload["projects"]}
            assert names == {f"OAuth token refresh pass {n}" for n in range(1, 9)}, (
                f"query='oauth' must match the eight OAuth projects case-insensitively; got {sorted(names)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_query_matches_the_taxonomy_alias_too(self, mcp_client, db_manager):
        """An agent that half-remembers a serial gets to the row from the serial."""
        client, tenant_key = mcp_client
        rows = _mixed_board()
        await _seed(db_manager, tenant_key, rows)
        try:
            everything = _payload(await _list_projects(client, include_completed=True))["projects"]
            alias = next(p["taxonomy_alias"] for p in everything if p.get("taxonomy_alias"))
            payload = _payload(await _list_projects(client, include_completed=True, query=alias))
            assert alias in {p["taxonomy_alias"] for p in payload["projects"]}, (
                f"query={alias!r} must find the row it names; got {payload['count']} rows"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_query_and_counts_together_answer_the_narrowing_question(self, mcp_client, db_manager):
        """The two moves compose, which is the whole point of building both.

        The counts block reports the board so the agent can see its search is narrow, and
        the search returns the few rows it asked for. Either alone leaves the agent
        guessing about the half it cannot see.
        """
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client, include_completed=True, query="billing"))
            assert payload["count"] == 1, f"query='billing' matches one row, got {payload['count']}"
            counts = payload.get("counts") or {}
            assert counts.get("total") == 10, (
                f"the counts must still describe the whole board while the page is narrow, got {counts!r}"
            )
            assert counts.get("returned") == 1, f"got {counts!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# CHARACTERIZATION -- passes on master; pins WHY a row cap is not a size bound.
# ---------------------------------------------------------------------------


class TestTheRowCeilingCannotBoundARicherProjection:
    async def test_one_planning_row_can_exceed_an_entire_ten_row_index_response(self, mcp_client, db_manager):
        """A row ceiling cannot bound a response whose rows are arbitrarily large.

        At ``depth >= 1`` (``mode='planning'|'audit'|'forensic'``) the projection adds the
        project's ``description`` and ``mission`` **in full and untruncated**
        (``_build_mcp_project_list``). So ``2,500 rows x unbounded row size`` is an
        unbounded response *regardless of the row cap* -- ``_MCP_LIST_PROJECT_CEILING`` is
        meaningful at depth 0 and close to decorative for every richer mode.

        This is why the counts block and a caller-facing ``limit`` are the fix and a
        bigger or smaller row number is not. It measures shipped behavior, so it passes
        before and after; it exists to stop the row cap from being mistaken for a size
        bound again.
        """
        client, tenant_key = mcp_client
        fat = _row(
            "One verbose project",
            "inactive",
            "2026-07-03",
            description="x" * 9000,
            mission="y" * 3000,
        )
        await _seed(db_manager, tenant_key, [fat, *_mixed_board()])
        try:
            index_rows = _payload(await _list_projects(client, include_completed=True))["projects"]
            planning_rows = _payload(await _list_projects(client, mode="planning"))["projects"]
            fat_row = next(r for r in planning_rows if r["name"] == "One verbose project")

            assert _wire_bytes(fat_row) > _wire_bytes(index_rows), (
                "a single depth>=1 row must be able to exceed an entire eleven-row index "
                f"response for the row cap to be a real size bound -- one row is "
                f"{_wire_bytes(fat_row)} B / {_tokens(fat_row)} tokens against "
                f"{_wire_bytes(index_rows)} B / {_tokens(index_rows)} tokens for the whole index list"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)
