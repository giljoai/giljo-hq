# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


@pytest.mark.skipif(platform.system() != "Windows", reason="Job Object is Windows-only")
def test_orphaned_child_killed_on_job_close() -> None:
    from giljo_mcp.process.win_job_object import WindowsJobObject

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(999)"])

    job = WindowsJobObject()
    job.assign(child.pid)

    job.close()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if child.poll() is not None:
            break
        time.sleep(0.05)

    exit_code = child.poll()
    assert exit_code is not None, (
        f"Child process (PID {child.pid}) still alive 2 s after job handle closed. "
        "Job Object containment is NOT working."
    )


@pytest.mark.skipif(platform.system() != "Windows", reason="Job Object is Windows-only")
def test_job_object_context_manager() -> None:
    from giljo_mcp.process.win_job_object import WindowsJobObject

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(999)"])

    with WindowsJobObject() as job:
        job.assign(child.pid)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if child.poll() is not None:
            break
        time.sleep(0.05)

    assert child.poll() is not None, f"Child (PID {child.pid}) still alive after context manager exit."
