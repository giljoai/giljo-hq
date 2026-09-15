# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.app_state import APIState
from giljo_mcp.branding import PRODUCT_NAME


def _quiet_state() -> APIState:
    state = APIState()
    state.heartbeat_task = None
    state.cleanup_task = None
    state.metrics_sync_task = None
    state.health_monitor = None
    state.silence_detector = None
    state.connections = {}
    state.websocket_broker = None
    state.db_manager = None
    return state


@pytest.mark.asyncio
async def test_shutdown_cancels_heartbeat_task():
    from api.startup.shutdown import shutdown

    state = APIState()

    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.heartbeat_task = asyncio.create_task(mock_task())

    await shutdown(state)

    assert state.heartbeat_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_cancels_cleanup_task():
    from api.startup.shutdown import shutdown

    state = APIState()

    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.cleanup_task = asyncio.create_task(mock_task())

    await shutdown(state)

    assert state.cleanup_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_cancels_metrics_sync_task():
    from api.startup.shutdown import shutdown

    state = APIState()

    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.metrics_sync_task = asyncio.create_task(mock_task())

    await shutdown(state)

    assert state.metrics_sync_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_handles_missing_tasks():
    from api.startup.shutdown import shutdown

    state = APIState()
    state.heartbeat_task = None
    state.cleanup_task = None
    state.metrics_sync_task = None
    state.health_monitor = None
    state.db_manager = None
    state.connections = {}

    await shutdown(state)


@pytest.mark.asyncio
async def test_shutdown_stops_health_monitor():
    from api.startup.shutdown import shutdown

    state = APIState()
    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock()
    state.connections = {}

    await shutdown(state)

    state.health_monitor.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_closes_websocket_connections():
    from api.startup.shutdown import shutdown

    state = APIState()

    mock_ws1 = MagicMock()
    mock_ws1.close = AsyncMock()
    mock_ws2 = MagicMock()
    mock_ws2.close = AsyncMock()

    state.connections = {"client1": mock_ws1, "client2": mock_ws2}

    await shutdown(state)

    mock_ws1.close.assert_awaited_once()
    mock_ws2.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_closes_database_connection():
    from api.startup.shutdown import shutdown

    state = APIState()
    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()
    state.connections = {}

    await shutdown(state)

    state.db_manager.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_continues_on_task_cancel_error():
    from api.startup.shutdown import shutdown

    state = APIState()

    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.heartbeat_task = asyncio.create_task(mock_task())
    state.connections = {}

    await shutdown(state)

    assert state.heartbeat_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_continues_on_error():
    from api.startup.shutdown import shutdown

    state = APIState()
    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock(side_effect=RuntimeError("Stop failed"))
    state.connections = {}
    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()

    with patch("api.startup.shutdown.logger") as mock_logger:
        await shutdown(state)

        exc_calls = [call.args[0] for call in mock_logger.exception.call_args_list]
        assert any("Error in shutdown step" in msg for msg in exc_calls)

        state.db_manager.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_logs_progress():
    from api.startup.shutdown import shutdown

    state = APIState()

    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.heartbeat_task = asyncio.create_task(mock_task())
    state.cleanup_task = None
    state.metrics_sync_task = None
    state.health_monitor = None
    state.connections = {}
    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()
    state.websocket_broker = None

    with patch("api.startup.shutdown.logger") as mock_logger:
        await shutdown(state)

        info_call_args = [call.args for call in mock_logger.info.call_args_list]

        assert any(
            "Shutting down %s API" in args[0] and args[1] == PRODUCT_NAME for args in info_call_args if len(args) > 1
        )
        assert any("Shutdown: %d/%d steps OK" in args[0] for args in info_call_args)


@pytest.mark.asyncio
async def test_shutdown_all_tasks_in_order():
    from api.startup.shutdown import shutdown

    state = APIState()
    execution_order = []

    async def mock_task():
        while True:
            await asyncio.sleep(1)

    original_task = asyncio.create_task(mock_task())

    original_cancel = original_task.cancel

    def tracked_cancel():
        execution_order.append("cancel_heartbeat")
        return original_cancel()

    original_task.cancel = tracked_cancel
    state.heartbeat_task = original_task

    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock(side_effect=lambda: execution_order.append("stop_health_monitor"))

    mock_ws = MagicMock()
    mock_ws.close = AsyncMock(side_effect=lambda: execution_order.append("close_websocket"))
    state.connections = {"client1": mock_ws}

    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock(side_effect=lambda: execution_order.append("close_database"))

    await shutdown(state)

    assert execution_order.index("cancel_heartbeat") < execution_order.index("stop_health_monitor")
    assert execution_order.index("stop_health_monitor") < execution_order.index("close_websocket")
    assert execution_order.index("close_websocket") < execution_order.index("close_database")




@pytest.mark.asyncio
async def test_shutdown_emits_at_most_three_info_lines_per_process(capsys, caplog):
    from api.startup.shutdown import shutdown

    state = _quiet_state()

    with caplog.at_level(logging.INFO, logger="api.startup.shutdown"):
        await shutdown(state)

    stdout_lines = [line for line in capsys.readouterr().out.replace("\r", "\n").splitlines() if line.strip()]
    info_records = [r for r in caplog.records if r.name == "api.startup.shutdown" and r.levelno >= logging.INFO]
    total = len(stdout_lines) + len(info_records)
    assert total <= 3, (
        f"shutdown emitted {total} INFO-level lines per process "
        f"(stdout={stdout_lines!r}, log={[r.getMessage() for r in info_records]!r})"
    )


@pytest.mark.asyncio
async def test_shutdown_step_detail_available_at_debug(caplog):
    from api.startup.shutdown import shutdown

    state = _quiet_state()

    with caplog.at_level(logging.DEBUG, logger="api.startup.shutdown"):
        await shutdown(state)

    debug_msgs = [
        r.getMessage() for r in caplog.records if r.name == "api.startup.shutdown" and r.levelno == logging.DEBUG
    ]
    for label in (
        "Background tasks",
        "Health monitor",
        "Silence detector",
        "WebSocket connections",
        "WebSocket broker",
        "Database",
    ):
        assert any(label in msg for msg in debug_msgs), f"step '{label}' not visible at DEBUG"


@pytest.mark.asyncio
async def test_shutdown_failed_step_named_at_warning_or_above(caplog):
    from api.startup.shutdown import shutdown

    state = _quiet_state()
    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock(side_effect=RuntimeError("stop failed"))

    with caplog.at_level(logging.INFO, logger="api.startup.shutdown"):
        await shutdown(state)

    warn_msgs = [
        r.getMessage() for r in caplog.records if r.name == "api.startup.shutdown" and r.levelno >= logging.WARNING
    ]
    assert any("Health monitor" in msg for msg in warn_msgs)
    assert any("Shutdown:" in msg and "Health monitor" in msg for msg in warn_msgs)
