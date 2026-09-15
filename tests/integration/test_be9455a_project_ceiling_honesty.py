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

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import _mcp_adapter_query_mixin as ceiling_mod
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


MEASURED_CEILING_FLOOR = 2500


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
                name=f"BE-9455A Product {uuid.uuid4().hex[:6]}",
                description="BE-9455 Symptom A -- the agent-facing project ceiling.",
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
                    description="Seeded for the ceiling reproduction.",
                    mission="Prove the cut selects on the axis the caller asked about.",
                    status=row["status"],
                    staging_status="staging_complete",
                    series_number=index,
                    created_at=_iso(row["created"]),
                    completed_at=_iso(row["completed"]) if row.get("completed") else None,
                )
            )
        await session.commit()

    return product_id


def _completion_dataset() -> tuple[str, list[dict]]:
    target_id = str(uuid.uuid4())
    rows = [
        {
            "id": str(uuid.uuid4()),
            "name": f"filler newest-created {n}",
            "created": f"2026-08-0{n}",
            "completed": f"2026-05-0{n}",
            "status": "completed",
        }
        for n in (1, 2, 3, 4)
    ]
    rows.append(
        {
            "id": target_id,
            "name": "OLD-created, MOST-RECENTLY-completed",
            "created": "2026-04-13",
            "completed": "2026-07-13",
            "status": "completed",
        }
    )
    return target_id, rows


async def _list_projects(client, **kwargs) -> object:
    async with client() as mcp_session:
        return await mcp_session.call_tool("list_projects", kwargs)


class TestTheCeilingKeepsTheRowsTheCallerAskedAbout:
    async def test_the_newest_completion_survives_the_ceiling(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            result = await _list_projects(client, include_completed=True)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            returned = [p["project_id"] for p in payload["projects"]]

            assert target_id in returned, (
                "the most recently completed project is ABSENT from a completion-oriented "
                "list -- the cap kept the newest-CREATED rows and dropped the newest-COMPLETED "
                f"one. returned {len(returned)} of {len(rows)} seeded rows: {returned!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_completion_oriented_list_is_ordered_by_completion(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 50)
        target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))
            returned = [p["project_id"] for p in payload["projects"]]

            assert returned[0] == target_id, (
                "a completion-oriented list must lead with the most recent completion "
                f"(2026-07-13); got order {[p['name'] for p in payload['projects']]!r}"
            )
            completions = [p["completed_at"] for p in payload["projects"]]
            assert completions == sorted(completions, reverse=True), (
                f"completion dates must descend, got {completions!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_mixed_query_never_drops_unfinished_work(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 3)
        unfinished = [
            {
                "id": str(uuid.uuid4()),
                "name": f"UNFINISHED created 2026-01-0{n}",
                "created": f"2026-01-0{n}",
                "completed": None,
                "status": "inactive",
            }
            for n in (1, 2)
        ]
        completed = [
            {
                "id": str(uuid.uuid4()),
                "name": f"completed 2026-07-0{n}",
                "created": f"2026-08-0{n}",
                "completed": f"2026-07-0{n}",
                "status": "completed",
            }
            for n in (1, 2, 3, 4)
        ]
        await _seed(db_manager, tenant_key, unfinished + completed)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))
            returned = {p["project_id"] for p in payload["projects"]}

            for row in unfinished:
                assert row["id"] in returned, (
                    "a mixed query must never drop unfinished work -- the cap has to fall on "
                    f"old completions, not on active projects. {row['name']!r} is absent; "
                    f"returned {[p['name'] for p in payload['projects']]!r}"
                )
            assert completed[3]["id"] in returned, (
                "the newest completion must survive alongside the unfinished work; "
                f"returned {[p['name'] for p in payload['projects']]!r}"
            )
            assert completed[0]["id"] not in returned, (
                "the OLDEST completion is what the cap should have discarded; "
                f"returned {[p['name'] for p in payload['projects']]!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_explicit_completed_status_query_is_completion_oriented_too(
        self, mcp_client, db_manager, monkeypatch
    ):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, status="completed"))
            returned = [p["project_id"] for p in payload["projects"]]
            assert target_id in returned, f"status='completed' dropped the newest completion. returned: {returned!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_default_active_list_still_truncates_on_creation(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 3)
        rows = [
            {
                "id": str(uuid.uuid4()),
                "name": f"unfinished created 2026-08-0{n}",
                "created": f"2026-08-0{n}",
                "completed": None,
                "status": "inactive",
            }
            for n in (1, 2, 3, 4, 5)
        ]
        newest_three = {rows[4]["id"], rows[3]["id"], rows[2]["id"]}
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client))
            returned = {p["project_id"] for p in payload["projects"]}
            assert returned == newest_three, (
                "an active-only list must still keep the newest-CREATED rows -- "
                f"expected the three newest, got {[p['name'] for p in payload['projects']]!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTruncationIsVisibleToTheCaller:
    async def test_a_truncated_response_says_so(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        _target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))

            assert payload.get("truncated") is True, (
                f"the response must tell the caller its list was cut short; got truncated={payload.get('truncated')!r}"
            )
            note = payload.get("truncation")
            assert isinstance(note, dict), f"a truncated response must carry a truncation detail block, got {note!r}"
            assert note.get("ceiling") == 4, f"the detail must name the ceiling that cut the list, got {note!r}"
            assert note.get("rows_fetched") == 4, f"the detail must state how many rows survived, got {note!r}"
            assert "completions" in note.get("dropped", ""), (
                f"the detail must say WHAT was dropped on a completion-oriented read, got {note!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_untruncated_response_says_it_was_not_truncated(self, mcp_client, db_manager, monkeypatch):
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 50)
        _target_id, rows = _completion_dataset()
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


class TestTheCeilingItself:
    async def test_the_ceiling_clears_the_measured_floor(self):
        assert ceiling_mod._MCP_LIST_PROJECT_CEILING >= MEASURED_CEILING_FLOOR, (
            f"the agent-facing ceiling is {ceiling_mod._MCP_LIST_PROJECT_CEILING}, below the "
            f"measured floor of {MEASURED_CEILING_FLOOR}"
        )
