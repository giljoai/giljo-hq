# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9477 -- ``patch_fields``: editing one roadmap field stops clearing the others.

The defect, measured rather than described: ``_upsert_many`` writes EVERY metadata
column from ``excluded`` unconditionally, and ``validate_items`` defaults every
omission (``sort_order``->0, ``risk``/``complexity``->NULL, ``blocked``->False). So a
row saved as *position 3 - risk high - complexity heavy - blocked "waiting on the
migration"*, resent as "this row, position 5", comes back with all four gone. It is
pinned on master, asserting the clobber, by
``test_be9474_roadmap_ergonomics_mcp_transport.py::test_resending_one_row_without_its_other_fields_clears_them``.

**The contract is the operator's, decided 2026-08-20 (Option A), and this file is
where it is enforced:**

- ``patch_fields`` OFF (the default) -- byte-identical to today. Every metadata
  column is written from the incoming row, omissions included.
- ``patch_fields`` ON -- an **omitted** key keeps its stored value; a key that is
  **present but empty/null** CLEARS that field. Omission and explicit-empty are
  therefore DIFFERENT instructions, which is why ``coalesce(excluded.x, table.x)``
  is foreclosed: it cannot express a clear at all.

Boundary, not service (house rule + BE-5042): the resend tax is paid by an agent
calling the MCP tool, so every assertion here runs through the in-memory FastMCP
transport. The fixture and seed helper are IMPORTED from the BE-9474 suite rather
than re-declared, so a red here is a red in the tool and never in a fixture this
file invented.

Edition Scope: Both (the MCP roadmap tool ships in CE and SaaS).
"""

from __future__ import annotations

import pytest

from tests.integration.test_be9474_roadmap_ergonomics_mcp_transport import (  # noqa: F401
    _error_text,
    _payload,
    _seed_product_with_aliased_rows,
    roadmap_mcp_client,
)


pytestmark = pytest.mark.asyncio


# The row shape a patch is measured against: every metadata column set to a
# non-default value, so a clobber of ANY of them is visible.
_FULL_ROW = {
    "sort_order": 0,
    "risk": "high",
    "complexity": "heavy",
    "blocked": True,
    "blocked_reason": "waiting on the migration",
}


async def _seed_full_row(session, project_id: str) -> None:
    """Save one roadmap row carrying every metadata field (flag OFF, today's path)."""
    result = await session.call_tool(
        "update_roadmap_metadata",
        {"items": [{"item_type": "project", "project_id": project_id, **_FULL_ROW}]},
    )
    assert result.is_error is False, _error_text(result)


async def _only_row(session) -> dict:
    after = await session.call_tool("get_roadmap", {})
    (row,) = _payload(after)["items"]
    return row


# ---------------------------------------------------------------------------
# BOTH-SIDES GUARDS -- these must pass before AND after the fix.
#
# If one of these goes red, suspect the instrument, not the diff: they assert
# behaviour this change does not touch. A fail-first file whose controls also
# fail has proved nothing.
# ---------------------------------------------------------------------------


async def test_control_a_full_row_still_lands_with_every_field(roadmap_mcp_client, db_session):  # noqa: F811
    """Control: the ordinary all-fields call is unaffected by this change."""
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
    """Control + the load-bearing back-compat pin: DEFAULT behaviour does not move.

    This is the same assertion BE-9474's ``test_resending_one_row_without_its_other_fields_clears_them``
    makes, restated here so the flag's OFF state is pinned in the file that adds
    the flag. It passes on master and MUST still pass after the fix -- the change
    is safe to land in an already-staged release precisely because an existing
    caller, which sends no ``patch_fields``, takes the identical path.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])

        moved = await session.call_tool(
            "update_roadmap_metadata",
            {"items": [{"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 5}]},
        )
        assert moved.is_error is False, _error_text(moved)
        row = await _only_row(session)

    assert row["sort_order"] == 5
    assert row["risk"] is None
    assert row["complexity"] is None
    assert row["blocked"] is False
    assert row["blocked_reason"] is None


# ---------------------------------------------------------------------------
# RED -- the acceptance assertions. These fail on master.
# ---------------------------------------------------------------------------


async def test_patch_mode_keeps_the_fields_the_item_did_not_carry(roadmap_mcp_client, db_session):  # noqa: F811
    """THE FIX: move one row and its other four fields survive.

    The operator-facing sentence this pins: a row reading *position 3 - risk high -
    complexity heavy - blocked "waiting on the migration"*, resent as "this row,
    position 5", comes back as *position 5* with everything else intact.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])

        moved = await session.call_tool(
            "update_roadmap_metadata",
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
    """Option A's other half: present-but-empty means CLEAR, not "leave it".

    Without this, patch mode would be a one-way ratchet -- an agent could set a
    risk and never take it off again without falling back to a full resend.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        await _seed_full_row(session, seed["project_ids"][0])

        cleared = await session.call_tool(
            "update_roadmap_metadata",
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
    # Untouched keys keep their stored values in the same call.
    assert row["sort_order"] == 0
    assert row["blocked"] is True
    assert row["blocked_reason"] == "waiting on the migration"


async def test_omitted_and_explicitly_empty_are_different_instructions(roadmap_mcp_client, db_session):  # noqa: F811
    """The whole point of the decision, in one assertion.

    Two rows in the SAME patch call, seeded identically. One omits ``risk``, the
    other sends ``risk: null``. If the implementation cannot tell "absent" from
    "present but null" -- which is exactly what ``coalesce(excluded.x, table.x)``
    cannot do -- these two rows come back identical and this fails.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)
    keeper, clearer = seed["project_ids"][0], seed["project_ids"][1]

    async with new_client() as session:
        seeded = await session.call_tool(
            "update_roadmap_metadata",
            {
                "items": [
                    {"item_type": "project", "project_id": keeper, **_FULL_ROW},
                    {"item_type": "project", "project_id": clearer, **_FULL_ROW},
                ]
            },
        )
        assert seeded.is_error is False, _error_text(seeded)

        patched = await session.call_tool(
            "update_roadmap_metadata",
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
    """A row that does not exist yet has nothing to preserve, so it takes defaults.

    Patch semantics apply to the UPDATE half of the upsert only. Without this
    pinned, a patch-mode insert could plausibly be read as "refuse a row with no
    stored value to patch" -- it is not; it inserts exactly as today.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        created = await session.call_tool(
            "update_roadmap_metadata",
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
    """``blocked`` and ``blocked_reason`` are ONE patchable unit, and half a pair is refused.

    They are not independent: an unblocked item carries no reason (the invariant
    ``_check_blocked`` has always enforced), and honouring that with half a pair
    present would need the row's stored state.

    The rule is deliberately OVER-BROAD and the reason is decidability, not
    damage. ``{blocked: true}`` alone is actually harmless -- the stored reason
    survives, because an unmentioned column never reaches the ``SET`` clause. But
    the other two single-key cases are valid or invalid depending on what is
    STORED, which the caller cannot see, so a permissive rule would accept or
    refuse the identical request based on invisible data. Refusing the whole
    half-pair is predictable from the payload every time. Full reasoning lives on
    ``roadmap_validation._check_patch_pairing``.

    This refusal exists ONLY in patch mode; no call that succeeds today is affected.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)
    pid = seed["project_ids"][0]

    async with new_client() as session:
        await _seed_full_row(session, pid)

        reason_only = await session.call_tool(
            "update_roadmap_metadata",
            {
                "items": [{"item_type": "project", "project_id": pid, "blocked_reason": "waiting on the auth gate"}],
                "patch_fields": True,
            },
        )
        blocked_only = await session.call_tool(
            "update_roadmap_metadata",
            {
                "items": [{"item_type": "project", "project_id": pid, "blocked": False}],
                "patch_fields": True,
            },
        )
        together = await session.call_tool(
            "update_roadmap_metadata",
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
    # The refusals changed nothing, and the well-formed pair applied.
    assert row["blocked"] is True
    assert row["blocked_reason"] == "waiting on the auth gate"
    assert row["risk"] == "high", "the refused calls must not have partially applied"


async def test_patch_mode_leaves_rows_it_was_not_sent_alone(roadmap_mcp_client, db_session):  # noqa: F811
    """Row-level scope is unchanged by field-level patching.

    BE-9474's refutation probe proved the tool was never full-replace at the ROW
    level. Restated under the flag so a future "patch" reading of the parameter
    cannot quietly start deleting unsent rows.
    """
    new_client, switch = roadmap_mcp_client
    seed = await _seed_product_with_aliased_rows(db_session, switch.value)

    async with new_client() as session:
        first = await session.call_tool(
            "update_roadmap_metadata",
            {
                "items": [
                    {"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 0},
                    {"item_type": "project", "project_id": seed["project_ids"][1], "sort_order": 1},
                ]
            },
        )
        assert first.is_error is False, _error_text(first)

        patched = await session.call_tool(
            "update_roadmap_metadata",
            {
                "items": [{"item_type": "project", "project_id": seed["project_ids"][2], "sort_order": 2}],
                "patch_fields": True,
            },
        )
        assert patched.is_error is False, _error_text(patched)

        after = await session.call_tool("get_roadmap", {})

    assert {row["project_id"] for row in _payload(after)["items"]} == set(seed["project_ids"][:3])


async def test_the_wire_advertises_patch_fields_and_its_contract(roadmap_mcp_client, db_session):  # noqa: F811
    """An agent must be able to LEARN the contract from the tool listing.

    A partial-update flag nobody is told about is a flag nobody uses. The
    description has to carry both halves -- omitted keeps, explicitly-empty
    clears -- because that distinction is the whole decision.
    """
    new_client, _ = roadmap_mcp_client

    async with new_client() as session:
        listing = await session.list_tools()

    tool = next(t for t in listing.tools if t.name == "update_roadmap_metadata")
    schema = tool.input_schema
    assert "patch_fields" in schema["properties"], "patch_fields must be on the wire"
    assert schema["properties"]["patch_fields"].get("default") is False, "the flag must default OFF on the wire"
    assert "patch_fields" not in schema.get("required", []), "the flag must be optional"

    blurb = schema["properties"]["patch_fields"]["description"].lower()
    assert "omit" in blurb, "the description must say what an omitted key does"
    assert "clear" in blurb, "the description must say that an explicitly empty value clears"
