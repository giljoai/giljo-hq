# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    from api.endpoints.mcp_session import MCPSessionManager

    tenant_key = _tk("noop")
    await _seed_session(db_session, tenant_key, "claude-code")

    with tenant_session_context(db_session, tenant_key):
        removed = await MCPSessionManager(db_session).delete_sessions_for_harness(
            tenant_key=tenant_key, harness="opencode"
        )

    assert removed == 0
    assert "claude-code" in await _harnesses(db_session, tenant_key)
