# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.download_tokens import TokenManager
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


async def _status(db_session: AsyncSession, token: str) -> str:
    return await db_session.scalar(text("SELECT staging_status FROM download_tokens WHERE token = :t"), {"t": token})


async def test_another_tenant_cannot_mark_a_token_ready(db_session: AsyncSession) -> None:
    manager = TokenManager(db_session)
    token = await manager.generate_token(TenantManager.generate_tenant_key(), "slash_commands", filename="f.zip")
    before = await _status(db_session, token)

    assert await manager.mark_ready(token, tenant_key=TenantManager.generate_tenant_key()) is False
    assert await _status(db_session, token) == before


async def test_another_tenant_cannot_mark_a_token_failed(db_session: AsyncSession) -> None:
    manager = TokenManager(db_session)
    token = await manager.generate_token(TenantManager.generate_tenant_key(), "slash_commands", filename="f.zip")
    before = await _status(db_session, token)

    assert await manager.mark_failed(token, "x", tenant_key=TenantManager.generate_tenant_key()) is False
    assert await _status(db_session, token) == before


async def test_the_owner_still_marks_ready(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    manager = TokenManager(db_session)
    token = await manager.generate_token(tenant_key, "slash_commands", filename="f.zip")

    assert await manager.mark_ready(token, tenant_key=tenant_key) is True
    assert await _status(db_session, token) == "ready"


async def test_the_health_monitor_loads_an_execution_only_within_its_tenant() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.dialects import postgresql

    from giljo_mcp.monitoring.agent_health_monitor import AgentHealthMonitor

    result = MagicMock()
    result.unique.return_value.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    status = MagicMock(execution_id="exec-1")

    await AgentHealthMonitor(MagicMock(), MagicMock())._handle_unhealthy_job(session, status, "tk_owner")

    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "agent_executions.tenant_key = 'tk_owner'" in sql, sql
