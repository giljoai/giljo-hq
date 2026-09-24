# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    async with client() as mcp_session:
        return await mcp_session.call_tool("list_tasks", kwargs)


def _wire_chars(payload: dict) -> int:
    from pydantic_core import to_json

    return len(to_json(payload, fallback=str).decode())




class TestTheCountsBlockIsTheKeystone:
    async def test_every_response_carries_a_counts_block(self, mcp_client, db_manager):
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
            assert (payload.get("truncated") is True) == (counts["returned"] < counts["matched"]), (
                f"truncated must hold iff returned < matched. truncated={payload.get('truncated')!r}, "
                f"returned={counts['returned']}, matched={counts['matched']}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_matched_reflects_the_filters_even_though_total_does_not(self, mcp_client, db_manager):
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




class TestTheListIsBounded:
    async def test_the_default_response_is_bounded(self, mcp_client, db_manager):
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
        client, tenant_key = mcp_client
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
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _corpus(3))

        try:
            result = await _list_tasks(client, limit=EXPECTED_MAX_LIMIT + 1)
            assert not result.is_error and "VALIDATION_ERROR" in _content_text(
                result
            ), (
                "a limit above the hard maximum must be refused at the boundary, the way "
                f"search_memory refuses one; got a successful response instead: {_content_text(result)!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)




class TestTheSizeBackstopDropsWholeRows:
    async def test_the_size_backstop_drops_whole_rows(self, mcp_client, db_manager):
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




class TestTheIndexRowIsLean:
    async def test_the_index_row_is_actually_leaner_in_bytes(self, mcp_client, db_manager):
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
                "created_at",
            }, f"the index row is the list-and-sort row and nothing more, got {sorted(row)!r}"
            assert row["type"] == "TSK", (
                "the type must be the plain abbreviation -- the embedded block repeats a "
                f"constant and a second UUID on every row to say 'TSK'. got {row['type']!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)




class TestQueryIsARealVerb:
    async def test_query_finds_a_task_by_a_word_in_its_title(self, mcp_client, db_manager):
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

            underscore = _payload(await _list_tasks(client, query="some_thing"))
            assert [t["task_id"] for t in underscore["tasks"]] == [underscore_id], (
                "'some_thing' must match literally -- an unescaped '_' is a single-character "
                f"wildcard. got {[t['task_id'] for t in underscore['tasks']]!r}"
            )

            bare = _payload(await _list_tasks(client, query="%"))
            assert [t["task_id"] for t in bare["tasks"]] == [percent_id], (
                "a bare '%' must be searched for as a character, not expanded to match every "
                f"row. got {len(bare['tasks'])} of {len(rows)} rows"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_query_also_matches_the_description(self, mcp_client, db_manager):
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




class TestNothingThatWorksTodayStopsWorking:
    async def test_an_unbounded_small_list_is_returned_whole(self, mcp_client, db_manager):
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
                "created_at",
            ):
                assert key in row, f"the shipped summary row key {key!r} must survive; got {sorted(row)!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_full_mode_still_carries_the_description(self, mcp_client, db_manager):
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
