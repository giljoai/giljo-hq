# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _run_start_api_server():
    import startup

    opened: dict[str, int] = {}
    captured: dict = {}

    def _capture_open(path, flags, *args, **kwargs):
        opened[str(path)] = flags
        return 123

    def _capture_popen(args, **kwargs):
        captured["kwargs"] = kwargs
        proc = MagicMock()
        proc.pid = 99999
        return proc

    patches = [
        patch("os.open", side_effect=_capture_open),
        patch("os.close", return_value=None),
        patch("subprocess.Popen", side_effect=_capture_popen),
        patch("platform.system", return_value="Linux"),
    ]
    for p in patches:
        p.start()
    try:
        proc = startup.start_api_server(verbose=False)
    finally:
        for p in patches:
            p.stop()
    return proc, opened, captured


def test_inf6022_api_stdout_log_opened_fresh_per_launch():
    proc, opened, _ = _run_start_api_server()

    assert proc is not None, (
        "start_api_server() returned None — the spawn path did not complete. "
        "Check that api/run_api.py exists and the stubs let execution reach Popen."
    )

    stdout_entries = [(path, flags) for path, flags in opened.items() if path.endswith("api_stdout.log")]
    assert stdout_entries, f"start_api_server() never opened logs/api_stdout.log. Paths opened: {list(opened)!r}"

    for path, flags in stdout_entries:
        assert flags & os.O_TRUNC, (
            f"{path} was opened without O_TRUNC (flags={flags}). INF-6022 requires "
            "truncating the live-view log each launch so the viewer shows the fresh "
            "session, not a replay of all prior runs."
        )
        assert not (flags & os.O_APPEND), (
            f"{path} was opened O_APPEND (flags={flags}) — that reintroduces the unbounded accumulation INF-6022 fixed."
        )


def test_inf6022_api_child_launched_unbuffered():
    proc, _, captured = _run_start_api_server()

    assert proc is not None, "start_api_server() returned None — spawn path did not complete."
    assert "kwargs" in captured, "subprocess.Popen was never called by start_api_server()."

    env = captured["kwargs"].get("env")
    assert env is not None, "start_api_server() launched the API child without an explicit env."
    assert env.get("PYTHONUNBUFFERED") == "1", (
        "API child env is missing PYTHONUNBUFFERED=1 (INF-6022 defensive). "
        f"Observed PYTHONUNBUFFERED={env.get('PYTHONUNBUFFERED')!r}."
    )
