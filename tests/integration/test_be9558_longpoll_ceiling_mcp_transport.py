# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
import time

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools import _base
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import PostgreSQLTestHelper

from tests.integration.test_be9296a_await_my_turn_mcp_boundary import wake_mcp_client  # noqa: F401


_POOL_TIMEOUT_SECONDS = 2.0
_SLOW_TOOL_HOLD_SECONDS = 3.0
_TEST_CEILING_SECONDS = 0.3


@pytest_asyncio.fixture
async def tiny_pool_engine():
    engine = create_async_engine(
        PostgreSQLTestHelper.get_test_db_url(),
        pool_size=1,
        max_overflow=0,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def slow_tool_client(tiny_pool_engine, monkeypatch):
    from api import app_state

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = object()

    async def _slow_workflow_status(*, project_id: str, tenant_key: str, exclude_job_id: str | None = None):
        async with tiny_pool_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await asyncio.sleep(_SLOW_TOOL_HOLD_SECONDS)
        return {"never": "reached in this test -- the ceiling must cancel first"}

    monkeypatch.setitem(_base.TOOL_DISPATCH, "get_workflow_status", lambda acc: _slow_workflow_status)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "HELD_TOOL_CEILING_SECONDS", _TEST_CEILING_SECONDS, raising=False)

    yield

    state.tool_accessor = prior_tool_accessor
    state.tenant_manager = prior_tenant_manager


@pytest.mark.asyncio
async def test_ceiling_cancels_slow_tool_call_and_frees_its_pool_connection(slow_tool_client, tiny_pool_engine):

    async def _hold_it():
        async with create_connected_server_and_client_session(mcp) as session:
            return await session.call_tool("get_workflow_status", {"project_id": "p1"})

    holder_task = asyncio.create_task(_hold_it())
    await asyncio.sleep(0.1)

    started = time.monotonic()
    ordinary_call_failed = False
    try:
        async with tiny_pool_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except SATimeoutError:
        ordinary_call_failed = True
    waited = time.monotonic() - started

    assert not ordinary_call_failed, (
        f"a concurrent ordinary caller was starved of the pool's only connection for "
        f"{waited:.2f}s and timed out -- the held tool call was never cancelled"
    )
    assert waited < _POOL_TIMEOUT_SECONDS, (
        f"ordinary caller waited {waited:.2f}s for a pool connection (pool_timeout="
        f"{_POOL_TIMEOUT_SECONDS}s) -- the held tool call was cancelled too late to help it"
    )

    holder_result = await holder_task
    assert holder_result.is_error is False, (
        f"the ceiling-exceeded response must be a Tier-2 structured rejection, not isError: {holder_result}"
    )
    payload = json.loads(holder_result.content[0].text)
    assert payload.get("error") == _base.TOOL_CEILING_ERROR, payload


@pytest.mark.asyncio
async def test_ceiling_does_not_clobber_get_my_turns_own_graceful_timeout(wake_mcp_client):  # noqa: F811
    client_factory, _tenant_key, _service = wake_mcp_client

    async with client_factory() as client:
        result = await client.call_tool("get_my_turn", {"agent_id": "worker-1", "wait_seconds": 1})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload.get("wake_reason") == "timeout", payload
    assert payload.get("error") != _base.TOOL_CEILING_ERROR, payload
