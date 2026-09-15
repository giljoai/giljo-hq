# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from api.startup import metrics_flushers
from api.startup.background_tasks import cleanup_expired_download_tokens
from api.startup.metrics_flushers import log_task_death, sync_api_metrics_to_db


def _fast_sleep(monkeypatch, max_iterations: int):
    real_sleep = asyncio.sleep
    calls = {"n": 0}

    async def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > max_iterations:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(metrics_flushers.asyncio, "sleep", fake_sleep)
    return calls


@pytest.mark.asyncio
async def test_api_metrics_flusher_survives_unexpected_error(monkeypatch, caplog):
    state = MagicMock()
    state.api_call_count = {"tk_test": 3}
    state.mcp_call_count = {}

    def _boom():
        raise RuntimeError("transient DB connect failure")

    state.db_manager.get_session_async = MagicMock(side_effect=_boom)

    calls = _fast_sleep(monkeypatch, max_iterations=3)

    with caplog.at_level(logging.ERROR, logger="api.startup.metrics_flushers"):
        with pytest.raises(asyncio.CancelledError):
            await sync_api_metrics_to_db(state)

    assert calls["n"] > 1
    assert any("Error during API metrics sync" in rec.message for rec in caplog.records)
    assert state.api_call_count == {"tk_test": 3}


@pytest.mark.asyncio
async def test_download_token_cleanup_survives_unexpected_error(monkeypatch, caplog):
    from api.startup import background_tasks

    state = MagicMock()

    def _boom():
        raise KeyError("outside the old narrow catch tuple")

    state.db_manager.get_session_async = MagicMock(side_effect=_boom)

    real_sleep = asyncio.sleep
    calls = {"n": 0}

    async def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > 3:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(background_tasks.asyncio, "sleep", fake_sleep)

    with caplog.at_level(logging.ERROR, logger="api.startup.background_tasks"):
        with pytest.raises(asyncio.CancelledError):
            await cleanup_expired_download_tokens(state)

    assert calls["n"] > 1
    assert any("Error during download token cleanup" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_log_task_death_logs_error_when_loop_dies(caplog):

    async def doomed():
        raise ValueError("escaped the loop")

    task = asyncio.get_running_loop().create_task(doomed(), name="doomed-loop")
    task.add_done_callback(log_task_death)
    with caplog.at_level(logging.ERROR, logger="api.startup.metrics_flushers"):
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0)

    assert any("maintenance_loop_died" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_log_task_death_logs_error_when_loop_returns(caplog):

    async def returns():
        return None

    task = asyncio.get_running_loop().create_task(returns(), name="returning-loop")
    task.add_done_callback(log_task_death)
    with caplog.at_level(logging.ERROR, logger="api.startup.metrics_flushers"):
        await task
        await asyncio.sleep(0)

    assert any("maintenance_loop_exited" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_log_task_death_silent_on_cancellation(caplog):

    async def forever():
        while True:
            await asyncio.sleep(3600)

    task = asyncio.get_running_loop().create_task(forever(), name="cancelled-loop")
    task.add_done_callback(log_task_death)
    await asyncio.sleep(0)
    task.cancel()
    with caplog.at_level(logging.ERROR, logger="api.startup.metrics_flushers"):
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    assert not any("maintenance_loop" in rec.message for rec in caplog.records)




@pytest.mark.asyncio
async def test_health_endpoint_exposes_degraded_services(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api.app_state import state
    from api.wiring.events import register_event_handlers

    app = FastAPI()
    register_event_handlers(app)
    monkeypatch.setattr(state, "degraded_services", ["backup_scheduler", "deletion_reaper"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["degraded_services"] == ["backup_scheduler", "deletion_reaper"]


@pytest.mark.asyncio
async def test_health_endpoint_omits_degraded_services_when_empty(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from api.app_state import state
    from api.wiring.events import register_event_handlers

    app = FastAPI()
    register_event_handlers(app)
    monkeypatch.setattr(state, "degraded_services", [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert "degraded_services" not in response.json()["checks"]
