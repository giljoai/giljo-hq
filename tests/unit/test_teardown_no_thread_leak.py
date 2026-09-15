# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import subprocess
import sys
import textwrap


def test_repeated_configure_logging_process_exits_cleanly():
    code = textwrap.dedent(
        """
        import logging
        from api import run_api
        for _ in range(3):
            run_api._configure_logging(log_level=logging.INFO)
        print("CLEAN_EXIT")
        """
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - regression signal
        raise AssertionError(
            "process hung at exit after repeated _configure_logging() — a "
            "lingering non-daemon thread / atexit deadlock has regressed"
        ) from exc

    assert "CLEAN_EXIT" in proc.stdout, proc.stderr
    assert proc.returncode == 0, proc.stderr


def test_config_file_watcher_observer_is_daemon(tmp_path):
    from giljo_mcp.config_manager import ConfigManager

    cm = ConfigManager(config_path=tmp_path / "config.yaml", auto_reload=False)
    cm._setup_file_watcher()
    try:
        assert cm._observer is not None
        assert cm._observer.daemon is True
    finally:
        cm.stop_watching()
