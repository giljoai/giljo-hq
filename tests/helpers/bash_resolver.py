# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.

"""Locate a bash that can actually run this repo's shell scripts.

Why this exists as a shared helper
==================================
Three test modules shell out to ``scripts/ci_guardrails.sh`` and each carried
its own byte-identical ``_resolve_bash()`` — one of them with the docstring
"Mirrors tests/unit/test_revision_id_guardrail.py", a copy that already knew it
was a copy. All three had the same defect, so all three had to be fixed, and
three separate fixes would have been three chances to diverge again.

The defect
==========
The old resolver selected bash by NAME: ``shutil.which("bash")``, first hit
wins. On Windows that very often resolves to ``C:\\Windows\\system32\\bash.EXE``
— the WSL launcher. It is a Linux bash inside the subsystem, where the drive is
mounted at ``/mnt/c``, so a Windows path is unreachable in EVERY spelling:
neither ``C:\\Users\\...`` nor ``C:/Users/...`` resolves. The script comes back
"No such file or directory" with exit 127, and because the backslashes are eaten
on the way in it reads like a quoting bug rather than the wrong interpreter.
Passing the path as ``as_posix()`` does not help — measured, WSL bash reports
NOTFOUND for both spellings.

Worse, the accompanying ``skipif(BASH is None)`` never fired, because a bash WAS
found. **The guard measured PRESENCE, not USABILITY**, so these tests failed
rather than skipping.

Whether it bites is decided by PATH ORDER in the shell that launched pytest, not
by the machine: on one session Git's ``usr/bin`` precedes ``system32`` and
everything passes, on another it follows and 24 tests fail — same box, same
commit. That is why a green local run does not clear this, and why the fix is a
usability probe rather than a preference for one install path.

The fix
=======
Validate the candidate BY USE: hand it a path that exists and require it to
agree. A name blocklist would only cover the System32 spelling; the probe covers
any bash that cannot reach the filesystem these tests operate on, and makes the
answer independent of PATH order. On Linux the first candidate passes the probe
immediately, so CI behaviour is unchanged by construction.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# Probe subject: a file every caller of this helper already depends on, so a
# passing probe proves the exact capability the callers need.
PROBE_PATH = REPO_ROOT / "scripts" / "ci_guardrails.sh"

# Tried BEFORE `shutil.which` on Windows, deliberately: it keeps the common case
# from spawning WSL just to reject it, which costs tens of seconds on a cold
# subsystem. Correctness does not depend on the order — the probe does — but
# speed does.
WINDOWS_GIT_BASH = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
)


def bash_can_see(candidate: str, probe: Path = PROBE_PATH) -> bool:
    """True when ``candidate`` can stat a path this process can see."""
    if not probe.is_file():
        # Nothing to probe with. Refusing here would report every bash unusable
        # and skip the suite green, which is the failure mode this module
        # exists to remove — so let the caller's own missing-script assert speak.
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
    """Return a bash that can reach this repo, or None if there is none."""
    candidates: list[str] = [c for c in WINDOWS_GIT_BASH if Path(c).is_file()]
    found = shutil.which("bash")
    if found:
        candidates.append(found)
    for candidate in candidates:
        if bash_can_see(candidate):
            return candidate
    return None


#: Resolved once per session. Immutable, so it is safe under pytest-xdist.
BASH = resolve_bash()

#: Skip marker for tests that shell out. Fires only when NO usable bash exists —
#: an honest "cannot run here" — never when one was found but is unusable, which
#: is the case that used to masquerade as a failure.
requires_bash = pytest.mark.skipif(
    BASH is None,
    reason="no bash on this platform that can reach the repo (Windows without Git Bash)",
)
