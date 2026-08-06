# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for shutdown module"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.app_state import APIState
from giljo_mcp.branding import PRODUCT_NAME


def _quiet_state() -> APIState:
    """An APIState with no live services -- a minimal simulated shutdown."""
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
    """Should cancel heartbeat task if present"""
    from api.startup.shutdown import shutdown

    state = APIState()

    # Create a proper async task that can be cancelled
    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.heartbeat_task = asyncio.create_task(mock_task())

    await shutdown(state)

    # Verify task was cancelled
    assert state.heartbeat_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_cancels_cleanup_task():
    """Should cancel cleanup task if present"""
    from api.startup.shutdown import shutdown

    state = APIState()

    # Create a proper async task that can be cancelled
    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.cleanup_task = asyncio.create_task(mock_task())

    await shutdown(state)

    # Verify task was cancelled
    assert state.cleanup_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_cancels_metrics_sync_task():
    """Should cancel metrics sync task if present"""
    from api.startup.shutdown import shutdown

    state = APIState()

    # Create a proper async task that can be cancelled
    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.metrics_sync_task = asyncio.create_task(mock_task())

    await shutdown(state)

    # Verify task was cancelled
    assert state.metrics_sync_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_handles_missing_tasks():
    """Should handle gracefully when tasks are None"""
    from api.startup.shutdown import shutdown

    state = APIState()
    state.heartbeat_task = None
    state.cleanup_task = None
    state.metrics_sync_task = None
    state.health_monitor = None
    state.db_manager = None
    state.connections = {}

    # Should not raise any errors
    await shutdown(state)


@pytest.mark.asyncio
async def test_shutdown_stops_health_monitor():
    """Should call health_monitor.stop() if monitor exists"""
    from api.startup.shutdown import shutdown

    state = APIState()
    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock()
    state.connections = {}

    await shutdown(state)

    # Verify stop was called
    state.health_monitor.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_closes_websocket_connections():
    """Should close all WebSocket connections in state.connections"""
    from api.startup.shutdown import shutdown

    state = APIState()

    # Create mock WebSocket connections
    mock_ws1 = MagicMock()
    mock_ws1.close = AsyncMock()
    mock_ws2 = MagicMock()
    mock_ws2.close = AsyncMock()

    state.connections = {"client1": mock_ws1, "client2": mock_ws2}

    await shutdown(state)

    # Verify both connections were closed
    mock_ws1.close.assert_awaited_once()
    mock_ws2.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_closes_database_connection():
    """Should call db_manager.close_async() if db_manager exists"""
    from api.startup.shutdown import shutdown

    state = APIState()
    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()
    state.connections = {}

    await shutdown(state)

    # Verify database connection was closed
    state.db_manager.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_continues_on_task_cancel_error():
    """Should handle CancelledError gracefully when awaiting cancelled tasks"""
    from api.startup.shutdown import shutdown

    state = APIState()

    # Create a proper async task that can be cancelled
    async def mock_task():
        while True:
            await asyncio.sleep(1)

    state.heartbeat_task = asyncio.create_task(mock_task())
    state.connections = {}

    # Should not propagate CancelledError
    await shutdown(state)

    # Test passes if no exception raised - task should be cancelled
    assert state.heartbeat_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_continues_on_error():
    """Should log errors but continue shutdown process"""
    from api.startup.shutdown import shutdown

    state = APIState()
    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock(side_effect=RuntimeError("Stop failed"))
    state.connections = {}
    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()

    with patch("api.startup.shutdown.logger") as mock_logger:
        # Should not raise, just log error
        await shutdown(state)

        # Verify error was logged via logger.exception (used by _run_with_timeout)
        exc_calls = [call.args[0] for call in mock_logger.exception.call_args_list]
        assert any("Error in shutdown step" in msg for msg in exc_calls)

        # Database should still close despite health monitor error
        state.db_manager.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_logs_progress():
    """Should log shutdown progress messages"""
    from api.startup.shutdown import shutdown

    state = APIState()

    # Create a proper async task mock that can be cancelled and awaited
    async def mock_task():
        while True:
            await asyncio.sleep(1)

    # Start the task so it's a real asyncio.Task
    state.heartbeat_task = asyncio.create_task(mock_task())
    state.cleanup_task = None
    state.metrics_sync_task = None
    state.health_monitor = None
    state.connections = {}
    state.db_manager = MagicMock()
    state.db_manager.close_async = AsyncMock()
    state.websocket_broker = None  # Avoid WebSocket broker shutdown logs

    with patch("api.startup.shutdown.logger") as mock_logger:
        await shutdown(state)

        # Verify shutdown messages were logged (step detail is at DEBUG, TSK-9194)
        info_call_args = [call.args for call in mock_logger.info.call_args_list]

        # The opening line is logged as logger.info("Shutting down %s API...", PRODUCT_NAME, ...)
        # -- assert the template AND that the interpolated product name is the
        # branding constant (not a hardcoded pre-rebrand product name).
        assert any(
            "Shutting down %s API" in args[0] and args[1] == PRODUCT_NAME for args in info_call_args if len(args) > 1
        )
        assert any("Shutdown: %d/%d steps OK" in args[0] for args in info_call_args)


@pytest.mark.asyncio
async def test_shutdown_all_tasks_in_order():
    """Should perform shutdown steps in correct order"""
    from api.startup.shutdown import shutdown

    state = APIState()
    execution_order = []

    # Create a proper async task
    async def mock_task():
        while True:
            await asyncio.sleep(1)

    # Track when task is cancelled
    original_task = asyncio.create_task(mock_task())

    # Wrap cancel to track execution
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

    # Verify order: tasks cancelled → health monitor stopped → websockets closed → database closed
    assert execution_order.index("cancel_heartbeat") < execution_order.index("stop_health_monitor")
    assert execution_order.index("stop_health_monitor") < execution_order.index("close_websocket")
    assert execution_order.index("close_websocket") < execution_order.index("close_database")


# --- TSK-9194: shutdown log-diet regression tests (incident 2026-07-16) ---
# The 6-step shutdown banner (progress lines x 4 uvicorn workers) burst past
# Railway's 500 logs/sec replica cap ("Messages dropped: 35") and destroyed the
# diagnostic tail. Shutdown must emit at most 3 lines per process at INFO;
# step detail lives at DEBUG; a failed step must still be named at WARNING+.


@pytest.mark.asyncio
async def test_shutdown_emits_at_most_three_info_lines_per_process(capsys, caplog):
    """A clean simulated shutdown emits <=3 INFO-level lines per process.

    Counts both logger records at INFO+ and stdout lines (print() output
    becomes an INFO-equivalent log line on non-TTY platform log collectors).
    """
    from api.startup.shutdown import shutdown

    state = _quiet_state()

    with caplog.at_level(logging.INFO, logger="api.startup.shutdown"):
        await shutdown(state)

    # \r-based progress rewrites still emit distinct log lines on non-TTY output
    stdout_lines = [line for line in capsys.readouterr().out.replace("\r", "\n").splitlines() if line.strip()]
    info_records = [r for r in caplog.records if r.name == "api.startup.shutdown" and r.levelno >= logging.INFO]
    total = len(stdout_lines) + len(info_records)
    assert total <= 3, (
        f"shutdown emitted {total} INFO-level lines per process "
        f"(stdout={stdout_lines!r}, log={[r.getMessage() for r in info_records]!r})"
    )


@pytest.mark.asyncio
async def test_shutdown_step_detail_available_at_debug(caplog):
    """Every shutdown step is still traceable by name at DEBUG level."""
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
    """A failing step is still reported at WARNING+ with the step name,
    and the end-of-shutdown summary names the failed step too."""
    from api.startup.shutdown import shutdown

    state = _quiet_state()
    state.health_monitor = MagicMock()
    state.health_monitor.stop = AsyncMock(side_effect=RuntimeError("stop failed"))

    with caplog.at_level(logging.INFO, logger="api.startup.shutdown"):
        await shutdown(state)

    warn_msgs = [
        r.getMessage() for r in caplog.records if r.name == "api.startup.shutdown" and r.levelno >= logging.WARNING
    ]
    # The step failure itself names the step
    assert any("Health monitor" in msg for msg in warn_msgs)
    # The summary line reports the failure with the step name
    assert any("Shutdown:" in msg and "Health monitor" in msg for msg in warn_msgs)
