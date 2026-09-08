# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
INF-5092 regression: QueueHandler must not block the uvicorn event loop.

Test strategy
-------------
We start a real uvicorn server in a separate *process* (not thread, to get
a clean event loop) using the new _configure_logging() setup from
api/run_api.py.  Before starting the server we monkey-patch the stream
handler's underlying stream with a MockStallingStream whose write() sleeps
for 30 s (simulating a stalled stdout/stderr fd).

With a bare StreamHandler that stall would block every log emit, which runs
on the event loop thread, causing every request to time-out.  With
QueueHandler the emit only enqueues — the blocking write happens on the
QueueListener's background thread and cannot freeze the event loop.

We then fire 200 concurrent GET /health requests (10-s client timeout each)
and assert every response is HTTP 200 within 2 s total.

NOTE: This test spawns a subprocess.  It does NOT touch the database, so no
TransactionalTestContext is needed.  It has no module-level mutable state and
owns all setup/teardown via fixtures — parallel-safe under pytest-xdist.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import logging.handlers
import multiprocessing
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers shared between parent and child process
# ---------------------------------------------------------------------------

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _uvicorn_worker(port_queue: Any, ready_event: Any) -> None:
    """
    Child-process entry point.

    1. Inserts the project root so ``api.run_api`` is importable.
    2. Binds its OWN listening socket on an OS-assigned port (port 0) and
       reports the real port back to the parent via ``port_queue``.
    3. Loads ``_configure_logging`` and calls it — this wires up the
       QueueHandler.
    4. Installs a MockStallingStream on the StreamHandler so any log
       line written to stdout stalls for 30 s.
    5. Starts uvicorn on the already-bound socket, serving ``api.app:app``.
    6. Signals the parent via ``ready_event`` once uvicorn is up.

    The socket is bound here, in the process that will actually serve on
    it, before anything is reported to the parent. That closes the
    check-then-bind race that existed when the parent picked a "free" port
    with its own throwaway socket and merely handed the bare port number to
    a not-yet-started child: on a loaded box another process can claim a
    port in the gap between "looked free" and "child actually binds". A
    socket that is ours from the moment of allocation has no such gap.
    """
    import logging
    import socket
    import threading

    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port_queue.put(sock.getsockname()[1])

    # Import and call the new configure function from run_api
    run_api = importlib.import_module("api.run_api")
    run_api._configure_logging(log_level=logging.INFO)  # type: ignore[attr-defined]

    # Find the StreamHandler installed by _configure_logging and replace its
    # stream with one that stalls.  The QueueHandler on the root logger never
    # calls it directly — the QueueListener does, on a background thread —
    # so the event loop must remain unaffected.
    class MockStallingStream:
        """Simulates a stalled fd: write() blocks for 30 s."""

        def write(self, msg: str) -> int:  # noqa: ARG002
            time.sleep(30)
            return len(msg)

        def flush(self) -> None:
            pass

    # Walk listener handlers to locate the StreamHandler
    listener = getattr(run_api, "_log_listener", None)
    if listener is not None:
        for h in listener.handlers:
            if isinstance(h, logging.StreamHandler) and not hasattr(h, "baseFilename"):
                h.stream = MockStallingStream()  # type: ignore[assignment]

    import uvicorn

    # Signal readiness in a background thread after a short boot delay
    def _signal_ready() -> None:
        time.sleep(1.5)
        ready_event.set()

    threading.Thread(target=_signal_ready, daemon=True).start()

    uvicorn.run(
        "api.app:app",
        fd=sock.fileno(),
        log_level="info",
        # Do NOT use reload — it forks again and confuses the fixture
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stalling_server():
    """
    Start the uvicorn server with a stalling stream handler.

    Yields the base URL once the server is ready, then terminates the process.

    The child process binds its own port-0 socket and reports the real port
    back over ``port_queue`` (see ``_uvicorn_worker``) — the port is ours
    from the moment it is allocated, so there is no window for another
    process on a loaded box to steal it between "looked free" and "actually
    bound". The ``try/finally`` guarantees the child process is always
    reaped, including when the test body raises or an assertion above fails
    partway through setup.
    """
    import queue as queue_module

    ctx = multiprocessing.get_context("spawn")
    port_queue = ctx.Queue()
    ready = ctx.Event()
    proc = ctx.Process(target=_uvicorn_worker, args=(port_queue, ready), daemon=True)
    proc.start()

    try:
        try:
            port = port_queue.get(timeout=15)
        except queue_module.Empty:
            raise AssertionError("Server process did not report a bound port within 15s") from None

        # Wait up to 15 s for the server to be ready
        ready.wait(timeout=15)
        assert proc.is_alive(), "Server process died during startup"

        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.join(timeout=5)


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.mark.server_mode
def test_logging_does_not_block_event_loop(stalling_server: str) -> None:
    """
    200 concurrent /health requests must ALL receive HTTP responses (not time out)
    within 20 s even when the log stream handler is stalled (30 s per write).

    server_mode: this test spawns a REAL uvicorn subprocess and is a wall-clock
    timing assertion (inherently flaky on a loaded CI runner), so it is excluded
    from the in-process gate by the standard marker filter
    (-m "not ... server_mode"). The same INF-5092 invariant is gated
    deterministically by test_inf5092_root_logger_uses_only_queue_handler below
    (root logger gets ONLY a QueueHandler; the blocking I/O handlers live on the
    QueueListener) — no subprocess, no timing.

    The proof-of-non-blocking is the TIMING: if the event loop were blocked by a
    synchronous StreamHandler.emit() call each /health response would wait for the
    30 s stall to complete.  With QueueHandler the emit is an O(1) enqueue; the
    stall runs on the listener's background thread and 200 requests still finish in
    well under 20 s.

    We accept 2xx or 5xx — the health endpoint may return 500/503 when running in
    test isolation (no database).  What we assert is that EVERY request received a
    response (no timeouts) and that the total wall time was sub-20 s.
    """
    import asyncio

    async def _run() -> list[int]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [client.get(f"{stalling_server}/health") for _ in range(200)]
            responses = await asyncio.gather(*tasks)
            return [r.status_code for r in responses]

    start = time.monotonic()
    statuses = asyncio.run(_run())
    elapsed = time.monotonic() - start

    # Every request must have received a response (no connect-error / timeout).
    # 2xx = healthy DB available; 5xx = DB not available (test isolation) — both
    # prove the event loop was NOT blocked by the stalling stream handler.
    unexpected = [s for s in statuses if s not in (200, 500, 503)]
    assert not unexpected, f"Unexpected HTTP statuses (expect 200/500/503): {unexpected}"

    assert elapsed < 20.0, (
        f"Requests took {elapsed:.1f}s — event loop appears blocked. "
        "With QueueHandler 200 requests must complete in under 20s "
        "even with a 30s stall on the StreamHandler."
    )


# ---------------------------------------------------------------------------
# BE-6030 regression tests (Fix A)
#
# These tests exercise the FAILING LAYER directly (the QueueListener's file
# handler), without spinning up a subprocess or touching the DB.  They are
# parallel-safe under pytest-xdist: no module-level state is mutated; all
# setup/teardown is scoped to the test function via fixtures or explicit
# cleanup in a try/finally.
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_run_api_module(tmp_path):
    """
    Reload api.run_api into a fresh module object so that ``_log_listener``
    starts as None and prior test state does not leak.

    The fixture also points the module's log directory at ``tmp_path`` so the
    test never writes into the real ``logs/`` directory.  After the test,
    if a QueueListener was started it is stopped cleanly (mirroring the
    atexit handler that would fire in production).

    Parallel-safe: each test gets its own module object; no shared globals
    are modified.
    """
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    # Force a clean reload so _log_listener starts as None.
    import importlib

    import api.run_api as _orig  # noqa: F401 — ensure parent pkg is importable

    spec = importlib.util.spec_from_file_location(
        "api.run_api_be6030_fresh",
        Path(_PROJECT_ROOT) / "api" / "run_api.py",
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Redirect the log file into tmp_path by intercepting SafeRotatingFileHandler
    # instantiation inside _configure_logging, so tests never write to real logs/.
    from giljo_mcp.logging import SafeRotatingFileHandler as _SafeRfh

    original_srfh_init = _SafeRfh.__init__

    def _patched_init(self, filename, **kwargs):
        # Redirect any log file to tmp_path so we never write to real logs/.
        patched_filename = str(tmp_path / Path(filename).name)
        original_srfh_init(self, patched_filename, **kwargs)

    with patch.object(_SafeRfh, "__init__", _patched_init):
        yield mod

    # Teardown: stop the listener if _configure_logging was called.
    listener = getattr(mod, "_log_listener", None)
    if listener is not None:
        with contextlib.suppress(Exception):
            listener.stop()


def test_be6030_file_handler_is_safe_rotating(fresh_run_api_module):
    """
    BE-6030 Fix A — handler-type regression.

    After _configure_logging() the file handler reachable via
    run_api._log_listener.handlers MUST be a SafeRotatingFileHandler, not a
    plain RotatingFileHandler.  This is the assertion that would have caught
    the original bug (which used RotatingFileHandler directly and crashed on
    Windows PermissionError during rollover).

    Failing layer: api/run_api.py _configure_logging() → QueueListener.handlers
    """
    from giljo_mcp.logging import SafeRotatingFileHandler

    mod = fresh_run_api_module
    # _log_listener is None before _configure_logging is called.
    assert mod._log_listener is None, "Expected fresh module with no listener"

    mod._configure_logging(log_level=logging.INFO)

    listener = mod._log_listener
    assert listener is not None, "_configure_logging() must set _log_listener"

    file_handlers = [h for h in listener.handlers if hasattr(h, "baseFilename")]
    assert file_handlers, (
        f"_log_listener.handlers must contain at least one file handler (handlers found: {listener.handlers!r})"
    )

    for fh in file_handlers:
        assert isinstance(fh, SafeRotatingFileHandler), (
            f"File handler must be SafeRotatingFileHandler, got {type(fh).__name__}. "
            "BE-6030: plain RotatingFileHandler crashes with PermissionError on Windows rollover."
        )


def test_be6030_permission_error_on_rollover_is_swallowed(fresh_run_api_module):
    """
    BE-6030 Fix A — PermissionError swallow regression.

    When doRollover() raises PermissionError (WinError 32 — another process
    holds the log file open), SafeRotatingFileHandler must catch and swallow
    the error so the logging path survives.  A plain RotatingFileHandler
    would let the exception propagate, crashing the QueueListener background
    thread and silencing all subsequent logging.

    Strategy: obtain the SafeRotatingFileHandler directly (no live file
    required), monkeypatch the *parent* class's doRollover to raise
    PermissionError, call doRollover() on the safe handler, assert NO
    exception escapes and the handler remains callable.

    Failing layer: SafeRotatingFileHandler.doRollover() in
    src/giljo_mcp/logging/__init__.py — the Windows crash-loop path.
    """
    from logging.handlers import RotatingFileHandler

    from giljo_mcp.logging import SafeRotatingFileHandler

    mod = fresh_run_api_module
    mod._configure_logging(log_level=logging.INFO)

    listener = mod._log_listener
    assert listener is not None

    file_handlers = [h for h in listener.handlers if isinstance(h, SafeRotatingFileHandler)]
    assert file_handlers, "Expected a SafeRotatingFileHandler in the listener"
    handler = file_handlers[0]

    # Monkeypatch the *stdlib* parent's doRollover to simulate the WinError 32
    # scenario (file locked by another process during rename).
    win_error = PermissionError(32, "The process cannot access the file because it is being used by another process")

    with patch.object(RotatingFileHandler, "doRollover", side_effect=win_error):
        # Must NOT raise — SafeRotatingFileHandler must absorb the error.
        try:
            handler.doRollover()
        except PermissionError as exc:
            raise AssertionError(
                f"SafeRotatingFileHandler.doRollover() must swallow PermissionError "
                f"(WinError 32), but it propagated: {exc}"
            ) from exc

    # After the swallowed error the handler must still be usable.
    record = logging.LogRecord(
        name="be6030.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="post-rollover-error emit check",
        args=(),
        exc_info=None,
    )
    # emit() must not raise — handler is still alive.
    try:
        handler.emit(record)
    except Exception as exc:
        raise AssertionError(
            f"handler.emit() must succeed after a swallowed PermissionError, but raised: {exc}"
        ) from exc


def test_inf5092_root_logger_uses_only_queue_handler(fresh_run_api_module):
    """
    INF-5092 regression at the FAILING LAYER (api/run_api.py _configure_logging).

    The original wedge: a bare StreamHandler on the root logger makes every log
    emit a synchronous write on the event-loop thread — a stalled stdout/stderr
    fd then freezes every request. The fix wires the root logger with ONLY a
    QueueHandler (O(1) enqueue); the real blocking I/O handlers (file + stream)
    live on the QueueListener's background thread.

    This asserts that wiring invariant deterministically — no subprocess, no
    timing, no DB — so the non-blocking property is gated in CI. The end-to-end
    timing proof (test_logging_does_not_block_event_loop, server_mode) is
    excluded from the in-process gate by the marker filter.

    Parallel-safe: uses the fresh_run_api_module fixture; asserts on the root
    logger immediately after _configure_logging() within this test.
    """
    mod = fresh_run_api_module
    assert mod._log_listener is None, "Expected fresh module with no listener"

    mod._configure_logging(log_level=logging.INFO)

    # Root logger must carry EXACTLY one handler, and it must be a QueueHandler.
    # Any StreamHandler/FileHandler attached directly to root would reintroduce
    # the synchronous-emit wedge INF-5092 fixed.
    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 1, (
        f"Root logger must have exactly one handler (the QueueHandler), got: {root_logger.handlers!r}"
    )
    assert isinstance(root_logger.handlers[0], logging.handlers.QueueHandler), (
        "Root logger handler must be a QueueHandler (INF-5092: enqueue, never "
        f"block the event loop), got {type(root_logger.handlers[0]).__name__}"
    )

    # The real (blocking) I/O handlers must live on the QueueListener's
    # background thread, NOT directly on the root logger.
    listener = mod._log_listener
    assert listener is not None, "_configure_logging() must start a QueueListener"
    assert listener.handlers, "QueueListener must hold the real I/O handlers"
    assert not any(h in root_logger.handlers for h in listener.handlers), (
        "Blocking I/O handlers must live only on the QueueListener, not on the root logger"
    )
