# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




def _wire_bytes(obj) -> int:
    return len(to_json(obj, fallback=str).decode())


def _tokens(obj) -> int:
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


def _iso(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T12:00:00+00:00")


async def _seed(db_manager, tenant_key: str, rows: list[dict]) -> str:
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
    completed = [
        _row(f"OAuth token refresh pass {n}", "completed", f"2026-0{n}-01", f"2026-0{n}-15") for n in range(1, 9)
    ]
    unfinished = [
        _row("Billing webhook retry", "inactive", "2026-07-01"),
        _row("Roadmap ordering polish", "inactive", "2026-07-02"),
    ]
    return completed + unfinished


async def _list_projects(client, **kwargs) -> object:
    async with client() as mcp_session:
        return await mcp_session.call_tool("list_projects", kwargs)




class TestTheHarnessItself:

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




class TestTheCheapProjectionIsActuallyCheap:
    async def test_triage_is_leaner_than_the_default_projection(self, mcp_client, db_manager):
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




class TestTheAnswerTeachesTheShapeOfTheNextQuestion:
    async def test_every_response_carries_a_counts_block(self, mcp_client, db_manager):
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
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            counts = _payload(await _list_projects(client)).get("counts")
            assert isinstance(counts, dict), f"there is no counts block to measure, got {counts!r}"
            cost = _tokens(counts)
            assert cost <= 200, f"the counts block costs {cost} tokens against a ~200 budget: {counts!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)




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
        client, tenant_key = mcp_client
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




class TestTheResponseSizeBackstop:

    async def test_a_size_cut_reports_response_size_and_says_a_bigger_limit_will_not_help(
        self, mcp_client, db_manager, monkeypatch
    ):
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

            triage = _payload(await _list_projects(client, mode="triage"))
            assert triage["count"] == 3, (
                "the advertised remedy must actually work: the lean row must return the "
                f"active-lifecycle rows the rich one could not. got {triage['count']}"
            )
            assert triage["truncated"] is False, f"the lean row fits comfortably; got {triage!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_response_under_the_ceiling_is_not_reported_as_size_cut(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        await _seed(db_manager, tenant_key, _mixed_board())
        try:
            payload = _payload(await _list_projects(client, include_completed=True, limit=50))
            assert payload["truncated"] is False, f"got {payload.get('truncated')!r}"
            assert "truncation" not in payload, f"got {payload.get('truncation')!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTheThreeWayPrecedence:

    async def test_size_beats_limit_when_both_bind(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(bounds_mod, "MCP_LIST_CHAR_CEILING", 3000)
        rows = [
            _row(f"verbose project {n}", "inactive", "2026-07-03", description="x" * 2000, mission="y" * 500)
            for n in range(8)
        ]
        await _seed(db_manager, tenant_key, rows)
        try:
            payload = _payload(await _list_projects(client, mode="planning", limit=5))
            assert payload["truncated"] is True
            assert payload["truncation"]["reason"] == "response_size", (
                "when the size bound and the limit both bit, size wins -- a bigger limit "
                f"returns the same payload. got {payload['truncation']!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_defensive_ceiling_beats_both(self, mcp_client, db_manager, monkeypatch):
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




class TestTheRowCeilingCannotBoundARicherProjection:
    async def test_one_planning_row_can_exceed_an_entire_ten_row_index_response(self, mcp_client, db_manager):
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
