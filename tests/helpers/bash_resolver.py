# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

PROBE_PATH = REPO_ROOT / "scripts" / "ci_guardrails.sh"

WINDOWS_GIT_BASH = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
)


def bash_can_see(candidate: str, probe: Path = PROBE_PATH) -> bool:
    if not probe.is_file():
        return True
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [candidate, "-c", 'test -f "$1"', "_", str(probe)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def resolve_bash() -> str | None:
    candidates: list[str] = [c for c in WINDOWS_GIT_BASH if Path(c).is_file()]
    found = shutil.which("bash")
    if found:
        candidates.append(found)
    for candidate in candidates:
        if bash_can_see(candidate):
            return candidate
    return None


BASH = resolve_bash()

requires_bash = pytest.mark.skipif(
    BASH is None,
    reason="no bash on this platform that can reach the repo (Windows without Git Bash)",
)
