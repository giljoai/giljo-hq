# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest
import websockets.exceptions
from fastapi import WebSocketDisconnect

from api.websocket import WebSocketManager


class _FakeWS:

    def __init__(
        self,
        *,
        fail: bool = False,
        hang_seconds: float | None = None,
        fail_exc: BaseException | None = None,
    ) -> None:
        self.fail = fail
        self.hang_seconds = hang_seconds
        self.fail_exc = fail_exc
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict) -> None:
        if self.hang_seconds is not None:
            await asyncio.sleep(self.hang_seconds)
        if self.fail_exc is not None:
            raise self.fail_exc
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(data)

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True




@pytest.mark.asyncio
async def test_heartbeat_supervisor_restarts_on_unexpected_death():
    from api.startup.core_services import _start_supervised_heartbeat

    calls = {"n": 0}
    alive = asyncio.Event()

    async def fake_start_heartbeat(interval: int = 30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("heartbeat boom")
        alive.set()
        await asyncio.sleep(3600)

    state = SimpleNamespace(
        websocket_manager=SimpleNamespace(start_heartbeat=fake_start_heartbeat),
        heartbeat_task=None,
    )

    _start_supervised_heartbeat(state, interval=30)

    await asyncio.wait_for(alive.wait(), timeout=2)
    assert calls["n"] == 2
    assert state.heartbeat_task is not None
    assert not state.heartbeat_task.done()

    state.heartbeat_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await state.heartbeat_task


@pytest.mark.asyncio
async def test_heartbeat_supervisor_does_not_resurrect_on_shutdown_cancel():
    from api.startup.core_services import _start_supervised_heartbeat

    calls = {"n": 0}

    async def fake_start_heartbeat(interval: int = 30):
        calls["n"] += 1
        await asyncio.sleep(3600)

    state = SimpleNamespace(
        websocket_manager=SimpleNamespace(start_heartbeat=fake_start_heartbeat),
        heartbeat_task=None,
    )

    _start_supervised_heartbeat(state, interval=30)
    task = state.heartbeat_task
    await asyncio.sleep(0)
    assert calls["n"] == 1

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    assert calls["n"] == 1
    assert state.heartbeat_task is task
    assert state.heartbeat_task.cancelled()




@pytest.mark.asyncio
async def test_send_heartbeat_delivers_to_all_and_drops_failures():
    mgr = WebSocketManager()
    ok1, ok2, bad = _FakeWS(), _FakeWS(), _FakeWS(fail=True)
    mgr.active_connections["a"] = ok1
    mgr.active_connections["b"] = ok2
    mgr.active_connections["c"] = bad

    await mgr.send_heartbeat()

    assert len(ok1.sent) == 1 and len(ok2.sent) == 1
    assert "c" not in mgr.active_connections
    assert "a" in mgr.active_connections and "b" in mgr.active_connections




@pytest.mark.asyncio
async def test_send_heartbeat_drops_client_on_websocket_disconnect():
    mgr = WebSocketManager()
    ok = _FakeWS()
    gone = _FakeWS(fail_exc=WebSocketDisconnect())
    mgr.active_connections["ok"] = ok
    mgr.active_connections["gone"] = gone

    await mgr.send_heartbeat()

    assert len(ok.sent) == 1
    assert "gone" not in mgr.active_connections
    assert "ok" in mgr.active_connections


@pytest.mark.asyncio
async def test_send_heartbeat_drops_client_on_connection_closed():
    mgr = WebSocketManager()
    ok = _FakeWS()
    gone = _FakeWS(fail_exc=websockets.exceptions.ConnectionClosedError(None, None))
    mgr.active_connections["ok"] = ok
    mgr.active_connections["gone"] = gone

    await mgr.send_heartbeat()

    assert len(ok.sent) == 1
    assert "gone" not in mgr.active_connections
    assert "ok" in mgr.active_connections


@pytest.mark.asyncio
async def test_start_heartbeat_loop_survives_unexpected_cycle_exception(monkeypatch):
    mgr = WebSocketManager()
    calls = {"n": 0}

    async def flaky_send_heartbeat():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated unexpected heartbeat failure")

    monkeypatch.setattr(mgr, "send_heartbeat", flaky_send_heartbeat)

    task = asyncio.create_task(mgr.start_heartbeat(interval=0))
    try:
        for _ in range(200):
            if calls["n"] >= 3:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert calls["n"] >= 3, "start_heartbeat must keep looping after a cycle raises"


@pytest.mark.asyncio
async def test_start_heartbeat_lets_cancelled_error_propagate_for_shutdown():
    mgr = WebSocketManager()

    async def slow_send_heartbeat():
        await asyncio.sleep(3600)

    mgr.send_heartbeat = slow_send_heartbeat  # type: ignore[method-assign]

    task = asyncio.create_task(mgr.start_heartbeat(interval=0))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
