# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression: .gitignore must not match any tracked file in the repo.

Class of bug this catches:
    A previously-tracked file (force-added past an unanchored .gitignore pattern)
    survives in private's history but gets silently dropped on every LAN/public
    export. The export script's final `git add -A` runs against a freshly-cloned
    tree where those files aren't yet tracked, so .gitignore takes effect and the
    file never reaches LAN Gitea or public GitHub.

    Original incident (2026-05-28): line 18 `downloads/` (Python boilerplate)
    silently stripped src/giljo_mcp/downloads/__init__.py and token_manager.py
    from every LAN export since the directory was added. Dogfood server couldn't
    import giljo_mcp.downloads.token_manager -> giljo_setup MCP call timed out.

Mechanism:
    Build a sandbox repo with our .gitignore and `git init`, then run
    `git check-ignore --no-index` against every path in `git ls-files`. Any
    match means a tracked file would be silently dropped by `git add -A` in a
    clean clone -- i.e., the LAN export would strip it.

Edition Scope: CE (infra concern affecting all exports).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# Only check tracked files that MUST reach the public/LAN export. Operator
# infra (audit/, private handover + tooling dirs, CLAUDE.md, .stignore, etc.) is
# intentionally both gitignored AND in .export-exclude -- those collisions
# are expected. Real source code being gitignored is the bug we're hunting.
SOURCE_PATH_PREFIXES = (
    "src/",
    "frontend/src/",
    "frontend/tests/",
    "api/",
    "migrations/",
    "tests/",
)

# Basenames intentionally tracked-and-gitignored-and-export-stripped. These
# collisions are by design (operator infra, not source code) and not the bug
# class this test guards.
EXPECTED_BENIGN_BASENAMES = frozenset({".stignore"})


def _git(args: list[str], cwd: Path) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout


def test_no_tracked_file_is_gitignored(tmp_path: Path) -> None:
    """Every tracked path must survive a fresh `git add -A` under our .gitignore.

    If this fails, the offending pattern is too broad. Either anchor it
    (`/foo/` instead of `foo/`) or whitelist the colliding path
    (`!src/giljo_mcp/foo/`).
    """
    all_tracked = _git(["ls-files"], REPO_ROOT).splitlines()
    tracked = [p for p in all_tracked if p.startswith(SOURCE_PATH_PREFIXES)]
    assert tracked, "no source-path tracked files found -- test setup wrong"

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    shutil.copy(REPO_ROOT / ".gitignore", sandbox / ".gitignore")
    _git(["init", "--quiet"], sandbox)

    # check-ignore --no-index --stdin reads NUL-delimited paths and prints
    # matched ones to stdout. Exit code 0 = at least one match, 1 = none.
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=sandbox,
        input="\0".join(tracked).encode(),
        capture_output=True,
        check=False,  # exit 1 = no matches, not an error
    )

    matched = [p for p in result.stdout.decode().split("\0") if p and Path(p).name not in EXPECTED_BENIGN_BASENAMES]
    assert not matched, (
        f"{len(matched)} tracked file(s) match .gitignore patterns and would be "
        f"silently dropped by `git add -A` on a fresh export clone:\n  "
        + "\n  ".join(matched[:20])
        + ("\n  ..." if len(matched) > 20 else "")
        + "\n\nFix: anchor the offending pattern in .gitignore to repo root "
        "(prefix with `/`) or add a whitelist `!path/to/file`."
    )


@pytest.mark.parametrize(
    "must_survive",
    [
        # Sentinel paths from the original 2026-05-28 incident. Hardcoded so
        # that any future regression resurrects the exact same symptom test.
        "src/giljo_mcp/downloads/__init__.py",
        "src/giljo_mcp/downloads/token_manager.py",
    ],
)
def test_known_silent_strip_victims_still_tracked(must_survive: str) -> None:
    """Belt-and-suspenders for the historical incident files."""
    tracked = set(_git(["ls-files"], REPO_ROOT).splitlines())
    assert must_survive in tracked, (
        f"{must_survive} is missing from `git ls-files`. This file was the "
        f"victim of the 2026-05-28 silent-strip bug and must remain tracked."
    )
