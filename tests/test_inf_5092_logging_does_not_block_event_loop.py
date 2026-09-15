# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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



_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _uvicorn_worker(port_queue: Any, ready_event: Any) -> None:
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

    run_api = importlib.import_module("api.run_api")
    run_api._configure_logging(log_level=logging.INFO)  # type: ignore[attr-defined]

    class MockStallingStream:

        def write(self, msg: str) -> int:  # noqa: ARG002
            time.sleep(30)
            return len(msg)

        def flush(self) -> None:
            pass

    listener = getattr(run_api, "_log_listener", None)
    if listener is not None:
        for h in listener.handlers:
            if isinstance(h, logging.StreamHandler) and not hasattr(h, "baseFilename"):
                h.stream = MockStallingStream()  # type: ignore[assignment]

    import uvicorn

    def _signal_ready() -> None:
        time.sleep(1.5)
        ready_event.set()

    threading.Thread(target=_signal_ready, daemon=True).start()

    uvicorn.run(
        "api.app:app",
        fd=sock.fileno(),
        log_level="info",
    )




@pytest.fixture(scope="module")
def stalling_server():
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

        ready.wait(timeout=15)
        assert proc.is_alive(), "Server process died during startup"

        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.join(timeout=5)




@pytest.mark.server_mode
def test_logging_does_not_block_event_loop(stalling_server: str) -> None:
    import asyncio

    async def _run() -> list[int]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [client.get(f"{stalling_server}/health") for _ in range(200)]
            responses = await asyncio.gather(*tasks)
            return [r.status_code for r in responses]

    start = time.monotonic()
    statuses = asyncio.run(_run())
    elapsed = time.monotonic() - start

    unexpected = [s for s in statuses if s not in (200, 500, 503)]
    assert not unexpected, f"Unexpected HTTP statuses (expect 200/500/503): {unexpected}"

    assert elapsed < 20.0, (
        f"Requests took {elapsed:.1f}s — event loop appears blocked. "
        "With QueueHandler 200 requests must complete in under 20s "
        "even with a 30s stall on the StreamHandler."
    )




@pytest.fixture
def fresh_run_api_module(tmp_path):
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    import importlib

    import api.run_api as _orig  # noqa: F401 — ensure parent pkg is importable

    spec = importlib.util.spec_from_file_location(
        "api.run_api_be6030_fresh",
        Path(_PROJECT_ROOT) / "api" / "run_api.py",
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    from giljo_mcp.logging import SafeRotatingFileHandler as _SafeRfh

    original_srfh_init = _SafeRfh.__init__

    def _patched_init(self, filename, **kwargs):
        patched_filename = str(tmp_path / Path(filename).name)
        original_srfh_init(self, patched_filename, **kwargs)

    with patch.object(_SafeRfh, "__init__", _patched_init):
        yield mod

    listener = getattr(mod, "_log_listener", None)
    if listener is not None:
        with contextlib.suppress(Exception):
            listener.stop()


def test_be6030_file_handler_is_safe_rotating(fresh_run_api_module):
    from giljo_mcp.logging import SafeRotatingFileHandler

    mod = fresh_run_api_module
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
    from logging.handlers import RotatingFileHandler

    from giljo_mcp.logging import SafeRotatingFileHandler

    mod = fresh_run_api_module
    mod._configure_logging(log_level=logging.INFO)

    listener = mod._log_listener
    assert listener is not None

    file_handlers = [h for h in listener.handlers if isinstance(h, SafeRotatingFileHandler)]
    assert file_handlers, "Expected a SafeRotatingFileHandler in the listener"
    handler = file_handlers[0]

    win_error = PermissionError(32, "The process cannot access the file because it is being used by another process")

    with patch.object(RotatingFileHandler, "doRollover", side_effect=win_error):
        try:
            handler.doRollover()
        except PermissionError as exc:
            raise AssertionError(
                f"SafeRotatingFileHandler.doRollover() must swallow PermissionError "
                f"(WinError 32), but it propagated: {exc}"
            ) from exc

    record = logging.LogRecord(
        name="be6030.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="post-rollover-error emit check",
        args=(),
        exc_info=None,
    )
    try:
        handler.emit(record)
    except Exception as exc:
        raise AssertionError(
            f"handler.emit() must succeed after a swallowed PermissionError, but raised: {exc}"
        ) from exc


def test_inf5092_root_logger_uses_only_queue_handler(fresh_run_api_module):
    mod = fresh_run_api_module
    assert mod._log_listener is None, "Expected fresh module with no listener"

    mod._configure_logging(log_level=logging.INFO)

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 1, (
        f"Root logger must have exactly one handler (the QueueHandler), got: {root_logger.handlers!r}"
    )
    assert isinstance(root_logger.handlers[0], logging.handlers.QueueHandler), (
        "Root logger handler must be a QueueHandler (INF-5092: enqueue, never "
        f"block the event loop), got {type(root_logger.handlers[0]).__name__}"
    )

    listener = mod._log_listener
    assert listener is not None, "_configure_logging() must start a QueueListener"
    assert listener.handlers, "QueueListener must hold the real I/O handlers"
    assert not any(h in root_logger.handlers for h in listener.handlers), (
        "Blocking I/O handlers must live only on the QueueListener, not on the root logger"
    )
