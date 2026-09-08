# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9591 half 1 — "Remove tool" must actually remove the connection.

THE DEFECT, from the operator's live test: clicking "Remove tool" on the Connect
page drops the card from the local fleet list and persists
``setup_selected_tools`` -- and touches nothing durable. Add the tool back and it
reads "Claude Code connected", green, purely from history.

``connected_harnesses`` derives entirely from ``mcp_sessions`` rows, so a removal
that leaves those rows behind removes nothing the status actually reads.

MATCHED ON THE RESOLVED HARNESS, NOT THE STORED NAME. The card is keyed by harness
token (``claude-code``); the row stores whatever clientInfo the client sent
(``giljo-qa-harness`` resolves to ``generic``). Removing the "Generic MCP client"
card therefore has to delete the rows that RESOLVE to generic, which is a resolver
question, not a string match. Reusing ``harness_from_client_info`` -- the same
resolver ``connected_harnesses`` reads with -- is what keeps removal and display
from disagreeing about which card a row belongs to.

SCOPE. Rows are matched by ``tenant_key`` plus resolved harness. Per ADR-009
``tenant_key`` is per-USER and permanently 1:1, so that IS "this user's rows";
adding a ``user_id`` predicate would be narrower than the display it has to
mirror and would strand rows whose ``user_id`` is NULL (the column is nullable) --
leaving ghosts that keep the card green after a removal.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, fresh
tenant per test. Edition Scope: Both.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import MCPSession
from giljo_mcp.repositories.auth_repository import AuthRepository


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9591_{suffix}_{uuid.uuid4().hex[:8]}"


async def _seed_session(db_session, tenant_key: str, client_name: str, user_id: str | None = None) -> str:
    """One mcp_sessions row carrying a client identity, as a real connect would leave.

    ``user_id`` defaults to NULL deliberately: the column is nullable, real rows can
    carry it, and a removal scoped by user_id would strand exactly these -- the ghosts
    that keep a card green after a removal. Seeding the awkward case is the point.
    """
    from api.endpoints.mcp_session import MCPSessionManager

    with tenant_session_context(db_session, tenant_key):
        row = await MCPSessionManager(db_session).create_session(
            tenant_key=tenant_key,
            user_id=user_id,
            client_info={"name": client_name, "version": "1.0.0"},
            auth_method="oauth_jwt",
        )
        return row.session_id


async def _harnesses(db_session, tenant_key: str) -> dict:
    with tenant_session_context(db_session, tenant_key):
        return await AuthRepository().connected_harnesses(db_session, tenant_key)


async def _row_count(db_session, tenant_key: str) -> int:
    with tenant_session_context(db_session, tenant_key):
        rows = await db_session.execute(select(MCPSession).where(MCPSession.tenant_key == tenant_key))
        return len(list(rows.scalars().all()))


async def test_removing_a_tool_clears_its_connection_rows(db_manager, db_session):
    """THE DEFECT: today the rows survive and the card stays green from history."""
    from api.endpoints.mcp_session import MCPSessionManager

    tenant_key = _tk("remove")
    await _seed_session(db_session, tenant_key, "claude-code")
    assert "claude-code" in await _harnesses(db_session, tenant_key)

    with tenant_session_context(db_session, tenant_key):
        removed = await MCPSessionManager(db_session).delete_sessions_for_harness(
            tenant_key=tenant_key, harness="claude-code"
        )

    assert removed == 1
    assert "claude-code" not in await _harnesses(db_session, tenant_key)


async def test_removing_one_tool_leaves_the_others_connected(db_manager, db_session):
    """The blast-radius control. Without it, a removal that dropped every row for the
    tenant would satisfy the test above while silently disconnecting every other tool."""
    from api.endpoints.mcp_session import MCPSessionManager

    tenant_key = _tk("scoped")
    await _seed_session(db_session, tenant_key, "claude-code")
    await _seed_session(db_session, tenant_key, "opencode")

    with tenant_session_context(db_session, tenant_key):
        await MCPSessionManager(db_session).delete_sessions_for_harness(tenant_key=tenant_key, harness="claude-code")

    remaining = await _harnesses(db_session, tenant_key)
    assert "opencode" in remaining
    assert "claude-code" not in remaining


async def test_removal_matches_the_resolved_harness_not_the_stored_name(db_manager, db_session):
    """Removing the "Generic MCP client" card must clear rows that RESOLVE to generic.

    ``giljo-qa-harness`` is not a recognised harness, so it displays on the generic
    card. A removal that string-matched the stored name would leave that row behind
    and the generic card would stay green with nothing the user can do about it.
    """
    from api.endpoints.mcp_session import MCPSessionManager

    tenant_key = _tk("generic")
    await _seed_session(db_session, tenant_key, "giljo-qa-harness")
    assert "generic" in await _harnesses(db_session, tenant_key)

    with tenant_session_context(db_session, tenant_key):
        removed = await MCPSessionManager(db_session).delete_sessions_for_harness(
            tenant_key=tenant_key, harness="generic"
        )

    assert removed == 1
    assert await _harnesses(db_session, tenant_key) == {}


async def test_removal_never_reaches_another_tenant(db_manager, db_session):
    """Tenant isolation on a DELETE path -- worth pinning, but read the caveat.

    MEASURED: removing the query's ``tenant_key`` predicate kills ZERO tests,
    including this one. The platform layer (the tenant-scoped session + its
    fail-closed guard) is what actually stops the cross-tenant read, not the
    predicate in this method -- the same finding two reviews reached
    independently on other queries.

    Kept anyway, unlike the unfalsifiable RLS assertion deleted in BE-9586c: this
    one pins a REAL user-visible property of a DELETE path (removing a tool for one
    account must not disconnect another's), and it is worth having a test that fails
    if that ever stops being true, whichever layer is enforcing it. What it does NOT
    prove is that this method's own predicate does the work -- so do not read a green
    here as licence to drop it. It stays because CLAUDE.md requires every query to
    filter by tenant_key, and because defence in depth on a DELETE is cheap.
    """
    from api.endpoints.mcp_session import MCPSessionManager

    mine = _tk("iso_mine")
    theirs = _tk("iso_theirs")
    await _seed_session(db_session, mine, "claude-code")
    await _seed_session(db_session, theirs, "claude-code")

    with tenant_session_context(db_session, mine):
        await MCPSessionManager(db_session).delete_sessions_for_harness(tenant_key=mine, harness="claude-code")

    assert await _row_count(db_session, mine) == 0
    assert await _row_count(db_session, theirs) == 1


async def test_removing_a_tool_that_was_never_connected_is_a_no_op(db_manager, db_session):
    """Idempotent: the UI may fire this for a card that has no rows, and that is not
    an error -- it is the state the user asked for."""
    from api.endpoints.mcp_session import MCPSessionManager

    tenant_key = _tk("noop")
    await _seed_session(db_session, tenant_key, "claude-code")

    with tenant_session_context(db_session, tenant_key):
        removed = await MCPSessionManager(db_session).delete_sessions_for_harness(
            tenant_key=tenant_key, harness="opencode"
        )

    assert removed == 0
    assert "claude-code" in await _harnesses(db_session, tenant_key)
