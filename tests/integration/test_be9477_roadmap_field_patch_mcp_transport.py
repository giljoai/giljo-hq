# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from tests.integration.test_be9474_roadmap_ergonomics_mcp_transport import (  # noqa: F401
    _error_text,
    _payload,
    _seed_product_with_aliased_rows,
    roadmap_mcp_client,
)


pytestmark = pytest.mark.asyncio


_FULL_ROW = {
    "sort_order": 0,
    "risk": "high",
    "complexity": "heavy",
    "blocked": True,
    "blocked_reason": "waiting on the migration",
}


async def _seed_full_row(session, project_id: str) -> None:
    result = await session.call_tool(
        "save_roadmap",
        {"items": [{"item_type": "project", "project_id": project_id, **_FULL_ROW}]},
    )
    assert result.is_error is False, _error_text(result)


async def _only_row(session) -> dict:
    after = await session.call_tool("get_roadmap", {})
    (row,) = _payload(after)["items"]
    return row




async def test_control_a_full_row_still_lands_with_every_field(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])
        row = await _only_row(session)

    assert row["sort_order"] == 0
    assert row["risk"] == "high"
    assert row["complexity"] == "heavy"
    assert row["blocked"] is True
    assert row["blocked_reason"] == "waiting on the migration"


async def test_control_b_flag_unset_still_clears_the_omitted_fields(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])

        moved = await session.call_tool(
            "save_roadmap",
            {"items": [{"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 5}]},
        )
        assert moved.is_error is False, _error_text(moved)
        row = await _only_row(session)

    assert row["sort_order"] == 5
    assert row["risk"] is None
    assert row["complexity"] is None
    assert row["blocked"] is False
    assert row["blocked_reason"] is None




async def test_patch_mode_keeps_the_fields_the_item_did_not_carry(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])

        moved = await session.call_tool(
            "save_roadmap",
            {
                "items": [{"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 5}],
                "patch_fields": True,
            },
        )
        assert moved.is_error is False, _error_text(moved)
        row = await _only_row(session)

    assert row["sort_order"] == 5
    assert row["risk"] == "high"
    assert row["complexity"] == "heavy"
    assert row["blocked"] is True
    assert row["blocked_reason"] == "waiting on the migration"


async def test_explicitly_empty_field_clears_it_in_patch_mode(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])

        cleared = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {
                        "item_type": "project",
                        "project_id": seed["project_ids"][0],
                        "risk": None,
                        "complexity": "",
                    }
                ],
                "patch_fields": True,
            },
        )
        assert cleared.is_error is False, _error_text(cleared)
        row = await _only_row(session)

    assert row["risk"] is None, "an explicitly null risk must CLEAR it"
    assert row["complexity"] is None, "an explicitly empty complexity must CLEAR it"
    assert row["sort_order"] == 0
    assert row["blocked"] is True
    assert row["blocked_reason"] == "waiting on the migration"


async def test_omitted_and_explicitly_empty_are_different_instructions(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)
    keeper, clearer = seed["project_ids"][0], seed["project_ids"][1]

    async with new_client() as session:
        seeded = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {"item_type": "project", "project_id": keeper, **_FULL_ROW},
                    {"item_type": "project", "project_id": clearer, **_FULL_ROW},
                ]
            },
        )
        assert seeded.is_error is False, _error_text(seeded)

        patched = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {"item_type": "project", "project_id": keeper, "sort_order": 1},
                    {"item_type": "project", "project_id": clearer, "sort_order": 2, "risk": None},
                ],
                "patch_fields": True,
            },
        )
        assert patched.is_error is False, _error_text(patched)

        after = await session.call_tool("get_roadmap", {})

    rows = {row["project_id"]: row for row in _payload(after)["items"]}
    assert rows[keeper]["risk"] == "high", "OMITTED risk must be kept"
    assert rows[clearer]["risk"] is None, "EXPLICITLY EMPTY risk must be cleared"
    assert rows[keeper]["risk"] != rows[clearer]["risk"], (
        "omitted and explicitly-empty must be DIFFERENT instructions -- if these "
        "agree, the implementation cannot distinguish absent from null"
    )


async def test_patch_mode_inserts_a_new_row_with_ordinary_defaults(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        created = await session.call_tool(
            "save_roadmap",
            {
                "items": [{"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 7}],
                "patch_fields": True,
            },
        )
        assert created.is_error is False, _error_text(created)
        row = await _only_row(session)

    assert row["sort_order"] == 7
    assert row["risk"] is None
    assert row["complexity"] is None
    assert row["blocked"] is False
    assert row["blocked_reason"] is None


async def test_block_state_and_its_note_must_be_patched_together(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)
    pid = seed["project_ids"][0]

    async with new_client() as session:
        await _seed_full_row(session, pid)

        reason_only = await session.call_tool(
            "save_roadmap",
            {
                "items": [{"item_type": "project", "project_id": pid, "blocked_reason": "waiting on the auth gate"}],
                "patch_fields": True,
            },
        )
        blocked_only = await session.call_tool(
            "save_roadmap",
            {
                "items": [{"item_type": "project", "project_id": pid, "blocked": False}],
                "patch_fields": True,
            },
        )
        together = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {
                        "item_type": "project",
                        "project_id": pid,
                        "blocked": True,
                        "blocked_reason": "waiting on the auth gate",
                    }
                ],
                "patch_fields": True,
            },
        )
        assert together.is_error is False, _error_text(together)
        row = await _only_row(session)

    assert reason_only.is_error is True, "blocked_reason without blocked must be refused"
    assert "blocked" in _error_text(reason_only)
    assert blocked_only.is_error is True, "blocked without blocked_reason must be refused"
    assert "blocked_reason" in _error_text(blocked_only)
    assert row["blocked"] is True
    assert row["blocked_reason"] == "waiting on the auth gate"
    assert row["risk"] == "high", "the refused calls must not have partially applied"


async def test_patch_mode_leaves_rows_it_was_not_sent_alone(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        first = await session.call_tool(
            "save_roadmap",
            {
                "items": [
                    {"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 0},
                    {"item_type": "project", "project_id": seed["project_ids"][1], "sort_order": 1},
                ]
            },
        )
        assert first.is_error is False, _error_text(first)

        patched = await session.call_tool(
            "save_roadmap",
            {
                "items": [{"item_type": "project", "project_id": seed["project_ids"][2], "sort_order": 2}],
                "patch_fields": True,
            },
        )
        assert patched.is_error is False, _error_text(patched)

        after = await session.call_tool("get_roadmap", {})

    assert {row["project_id"] for row in _payload(after)["items"]} == set(seed["project_ids"][:3])


async def test_the_wire_advertises_patch_fields_and_its_contract(roadmap_mcp_client, db_session):  # noqa: F811
    new_client, _ = roadmap_mcp_client

    async with new_client() as session:
        listing = await session.list_tools()

    tool = next(t for t in listing.tools if t.name == "save_roadmap")
    schema = tool.input_schema
    assert "patch_fields" in schema["properties"], "patch_fields must be on the wire"
    assert schema["properties"]["patch_fields"].get("default") is False, "the flag must default OFF on the wire"
    assert "patch_fields" not in schema.get("required", []), "the flag must be optional"

    blurb = schema["properties"]["patch_fields"]["description"].lower()
    assert "omit" in blurb, "the description must say what an omitted key does"
    assert "clear" in blurb, "the description must say that an explicitly empty value clears"
