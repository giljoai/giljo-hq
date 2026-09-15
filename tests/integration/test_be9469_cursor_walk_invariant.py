# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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


_KEEP_CREATED_AFTER = "2026-07-20T00:00:00+00:00"


async def _seed_filtered_run(db_manager, tenant_key: str) -> list[str]:
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
                    created_at=_day(25) if is_wanted else datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
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

    async def test_a_project_walk_returns_every_row_exactly_once(self, mcp_client, db_manager):
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
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=8, finished=0, tie_size=0)

        try:
            seen, _ = await _walk(client, "list_projects", "projects", "project_id", limit=PAGE, mode="triage")
            assert len(seen) == len(set(seen)), f"duplicates: {[i for i in seen if seen.count(i) > 1]!r}"
            assert set(seen) == set(seeded), f"missing {sorted(set(seeded) - set(seen))!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_without_a_cursor_the_same_call_never_advances(self, mcp_client, db_manager):
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

    async def test_a_call_without_a_cursor_is_unchanged(self, mcp_client, db_manager):
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
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=2, finished=3, tie_size=3)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            assert "next_cursor" not in payload, "next_cursor must not be a top-level response key"
            assert payload["truncation"]["next_cursor"]
            for key in ("reason", "ceiling", "rows_fetched", "dropped", "advice"):
                assert key in payload["truncation"], f"the shipped truncation key {key!r} is gone"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_advice_names_the_token_when_one_exists(self, mcp_client, db_manager):
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

    async def test_replaying_a_cursor_under_changed_filters_is_refused(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=3, finished=4, tie_size=4)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token = first["truncation"]["next_cursor"]

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
        client, tenant_key = mcp_client
        seeded = await _seed_projects(db_manager, tenant_key, unfinished=3, finished=4, tie_size=4)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token = first["truncation"]["next_cursor"]
            seen = [p["project_id"] for p in first["projects"]]

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

    async def test_a_cursor_from_another_tenant_cannot_read_across_the_boundary(self, mcp_client, db_manager):
        client, tenant_a = mcp_client
        tenant_b = TenantManager.generate_tenant_key()
        a_ids = await _seed_projects(db_manager, tenant_a, unfinished=2, finished=3, tie_size=3)
        b_ids = await _seed_projects(db_manager, tenant_b, unfinished=2, finished=3, tie_size=3)

        try:
            first = _payload(await _call(client, "list_projects", include_completed=True, limit=2, mode="triage"))
            token_from_a = first["truncation"]["next_cursor"]

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

    async def test_a_whole_rejected_window_between_two_matches_is_crossed(self, mcp_client, db_manager, monkeypatch):
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

    async def test_the_same_row_yields_the_same_token_in_every_mode(self, mcp_client, db_manager):
        client, tenant_key = mcp_client
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
        import base64

        client, tenant_key = mcp_client
        await _seed_projects(db_manager, tenant_key, unfinished=1, finished=4, tie_size=4)

        try:
            payload = _payload(await _call(client, "list_projects", include_completed=True, limit=3, mode="triage"))
            token = payload["truncation"]["next_cursor"]
            decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            assert decoded["s"] is not None, f"the cursor carries no position: {decoded!r}"
            datetime.fromisoformat(decoded["s"])

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
    import base64

    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    del payload["s"]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


class TestAMissingPositionKeyIsRefusedNotCrashed:

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
