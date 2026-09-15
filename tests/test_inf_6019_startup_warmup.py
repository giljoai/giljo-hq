# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Self
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.app import _warm_up


class _FakeAsyncSession:

    def __init__(self) -> None:
        self.execute = AsyncMock()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


@pytest.mark.asyncio
async def test_warm_up_pings_db_and_configures_mappers(monkeypatch):
    monkeypatch.setenv("GILJO_WARM_DB_CONNECTIONS", "1")
    called = {"configure_mappers": 0}
    monkeypatch.setattr(
        "sqlalchemy.orm.configure_mappers",
        lambda: called.__setitem__("configure_mappers", called["configure_mappers"] + 1),
    )
    session = _FakeAsyncSession()
    state = SimpleNamespace(db_manager=SimpleNamespace(AsyncSessionLocal=lambda: session))

    await _warm_up(state)

    assert called["configure_mappers"] == 1
    session.execute.assert_awaited_once()
    sent_sql = str(session.execute.await_args.args[0])
    assert "SELECT 1" in sent_sql


@pytest.mark.asyncio
async def test_warm_up_opens_multiple_pooled_connections(monkeypatch):
    monkeypatch.setenv("GILJO_WARM_DB_CONNECTIONS", "4")
    monkeypatch.setattr("sqlalchemy.orm.configure_mappers", lambda: None)

    opened: list[_FakeAsyncSession] = []

    def _factory() -> _FakeAsyncSession:
        session = _FakeAsyncSession()
        opened.append(session)
        return session

    state = SimpleNamespace(db_manager=SimpleNamespace(AsyncSessionLocal=_factory))

    await _warm_up(state)

    assert len(opened) == 4
    for session in opened:
        session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_warm_up_never_raises_on_db_failure_and_logs_error(monkeypatch, caplog):
    monkeypatch.setattr("sqlalchemy.orm.configure_mappers", lambda: None)
    state = SimpleNamespace(
        db_manager=SimpleNamespace(AsyncSessionLocal=MagicMock(side_effect=RuntimeError("db down")))
    )
    with caplog.at_level(logging.ERROR):
        await _warm_up(state)
    assert any(r.levelno == logging.ERROR for r in caplog.records), "warm-up failure must log at ERROR"


@pytest.mark.asyncio
async def test_warm_up_tolerates_missing_db_manager(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("sqlalchemy.orm.configure_mappers", lambda: calls.__setitem__("n", calls["n"] + 1))
    state = SimpleNamespace(db_manager=None)
    await _warm_up(state)
    assert calls["n"] == 1
