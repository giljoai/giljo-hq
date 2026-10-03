# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from api.endpoints.mcp_session import MCPSessionManager
from giljo_mcp.auth.dependencies import _record_api_key_usage
from giljo_mcp.auth.ip_logger import log_api_key_ip


def _db_down() -> OperationalError:
    return OperationalError("INSERT", {}, Exception("connection reset"))


def _session(exc: Exception) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=exc)
    db.info = {}
    return db


@pytest.mark.asyncio
async def test_ip_logger_rolls_the_shared_session_back_on_a_database_error():
    db = _session(_db_down())
    await log_api_key_ip(db, "key-1", "203.0.113.9")
    db.rollback.assert_awaited_once()
    with pytest.raises(TypeError):
        await log_api_key_ip(_session(TypeError("bug")), "key-1", "203.0.113.9")


@pytest.mark.asyncio
async def test_rest_usage_bookkeeping_rolls_back_and_does_not_hide_a_bug():
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"))
    db = _session(_db_down())
    await _record_api_key_usage(db, request, "key-1")
    db.rollback.assert_awaited_once()
    with pytest.raises(TypeError):
        await _record_api_key_usage(_session(TypeError("bug")), request, "key-1")


@pytest.mark.asyncio
async def test_mcp_ip_logging_rolls_back_and_does_not_hide_a_bug():
    db = _session(_db_down())
    await MCPSessionManager(db).log_ip(f"key-{id(db)}", "203.0.113.9")
    db.rollback.assert_awaited_once()
    with pytest.raises(TypeError):
        await MCPSessionManager(_session(TypeError("bug"))).log_ip("key-2", "203.0.113.9")
