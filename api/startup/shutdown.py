# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Shutdown module

Handles graceful shutdown of all services and connections.
Each step has a timeout to prevent hanging on unresponsive services.

Log diet (TSK-9194, incident 2026-07-16): the per-step progress banner burst
past Railway's 500 logs/sec replica cap when 4 uvicorn workers shut down at
once, dropping the diagnostic tail. Shutdown now emits at most 3 lines per
process at INFO (opening line + one summary line); per-step detail lives at
DEBUG, and a failed or timed-out step is still named at WARNING+.
"""

import asyncio
import contextlib
import logging
import time

from api.app_state import APIState
from giljo_mcp.branding import PRODUCT_NAME


logger = logging.getLogger(__name__)

# Maximum seconds to wait for each shutdown step before force-skipping
STEP_TIMEOUT = 5


async def _run_with_timeout(coro, step_name: str, timeout: float = STEP_TIMEOUT) -> bool:
    """Run a coroutine with a timeout. Returns True if completed, False if timed out."""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return True
    except TimeoutError:
        logger.warning(f"Shutdown step '{step_name}' timed out after {timeout}s - forcing skip")
        return False
    except (RuntimeError, OSError, ConnectionError, ValueError):  # Shutdown resilience
        logger.exception("Error in shutdown step '%s'", step_name)
        return False


def _finish_step(step: int, total: int, label: str, ok: bool, elapsed: float, failed: list[str]) -> None:
    """Record a completed shutdown step: detail at DEBUG, failures accumulated."""
    logger.debug(
        "Shutdown step (%d/%d) %s: %s (%.1fs)",
        step,
        total,
        label,
        "OK" if ok else "FAILED",
        elapsed,
    )
    if not ok:
        failed.append(label)


async def shutdown(state: APIState) -> None:
    """Gracefully shutdown all services with timeouts and per-step detail at DEBUG.

    Each step has a 5-second timeout. If a step hangs, it is skipped
    and shutdown continues. Total worst-case shutdown time: ~30 seconds.

    Args:
        state: APIState instance with active services and connections
    """
    total_steps = 6
    failed: list[str] = []
    t_start = time.monotonic()
    logger.info(
        "Shutting down %s API (%d steps, %ds timeout each)...",
        PRODUCT_NAME,
        total_steps,
        STEP_TIMEOUT,
    )

    # Step 1: Cancel background tasks
    step = 1
    label = "Background tasks"
    logger.debug("Shutdown step (%d/%d) %s...", step, total_steps, label)
    t0 = time.monotonic()
    try:
        tasks_to_cancel = []
        for task_attr in (
            "heartbeat_task",
            "cleanup_task",
            "metrics_sync_task",
            # FE-9202 F3: cancel the 6-hourly banner refresh on shutdown; the
            # update-checker task had the same missing-cancel gap on this line.
            "system_banner_refresh_task",
            "update_checker_task",
        ):
            task = getattr(state, task_attr, None)
            if task:
                task.cancel()
                tasks_to_cancel.append(task)
        if tasks_to_cancel:
            done = await _run_with_timeout(
                asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                label,
            )
        else:
            done = True
    except (RuntimeError, OSError, ConnectionError, ValueError):  # Shutdown resilience
        logger.exception("Error in shutdown step '%s'", label)
        done = False
    _finish_step(step, total_steps, label, done, time.monotonic() - t0, failed)

    # Step 2: Stop health monitor
    step = 2
    label = "Health monitor"
    logger.debug("Shutdown step (%d/%d) %s...", step, total_steps, label)
    t0 = time.monotonic()
    if state.health_monitor:
        done = await _run_with_timeout(state.health_monitor.stop(), label)
    else:
        done = True
    _finish_step(step, total_steps, label, done, time.monotonic() - t0, failed)

    # Step 3: Stop silence detector
    step = 3
    label = "Silence detector"
    logger.debug("Shutdown step (%d/%d) %s...", step, total_steps, label)
    t0 = time.monotonic()
    if getattr(state, "silence_detector", None):
        done = await _run_with_timeout(state.silence_detector.stop(), label)
    else:
        done = True
    _finish_step(step, total_steps, label, done, time.monotonic() - t0, failed)

    # Step 4: Close WebSocket connections
    step = 4
    label = "WebSocket connections"
    logger.debug("Shutdown step (%d/%d) %s...", step, total_steps, label)
    t0 = time.monotonic()
    ws_count = len(state.connections)

    async def close_all_ws():
        for ws in list(state.connections.values()):
            with contextlib.suppress(Exception):
                await ws.close()

    if ws_count > 0:
        done = await _run_with_timeout(close_all_ws(), label)
    else:
        done = True
    _finish_step(step, total_steps, f"{label} ({ws_count})", done, time.monotonic() - t0, failed)

    # Step 5: Stop WebSocket broker
    step = 5
    label = "WebSocket broker"
    logger.debug("Shutdown step (%d/%d) %s...", step, total_steps, label)
    t0 = time.monotonic()
    if getattr(state, "websocket_broker", None):
        done = await _run_with_timeout(state.websocket_broker.stop(), label)
    else:
        done = True
    _finish_step(step, total_steps, label, done, time.monotonic() - t0, failed)

    # Step 6: Close database
    step = 6
    label = "Database"
    logger.debug("Shutdown step (%d/%d) %s...", step, total_steps, label)
    t0 = time.monotonic()
    if state.db_manager:
        done = await _run_with_timeout(state.db_manager.close_async(), label)
    else:
        done = True
    _finish_step(step, total_steps, label, done, time.monotonic() - t0, failed)

    elapsed_total = time.monotonic() - t_start
    if failed:
        logger.warning(
            "Shutdown: %d/%d steps OK in %.1fs (failed: %s)",
            total_steps - len(failed),
            total_steps,
            elapsed_total,
            ", ".join(failed),
        )
    else:
        logger.info("Shutdown: %d/%d steps OK in %.1fs", total_steps, total_steps, elapsed_total)
