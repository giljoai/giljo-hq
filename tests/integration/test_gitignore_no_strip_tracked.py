# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_PATH_PREFIXES = (
    "src/",
    "frontend/src/",
    "frontend/tests/",
    "api/",
    "migrations/",
    "tests/",
)

EXPECTED_BENIGN_BASENAMES = frozenset({".stignore"})


def _git(args: list[str], cwd: Path) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout


def test_no_tracked_file_is_gitignored(tmp_path: Path) -> None:
    all_tracked = _git(["ls-files"], REPO_ROOT).splitlines()
    tracked = [p for p in all_tracked if p.startswith(SOURCE_PATH_PREFIXES)]
    assert tracked, "no source-path tracked files found -- test setup wrong"

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    shutil.copy(REPO_ROOT / ".gitignore", sandbox / ".gitignore")
    _git(["init", "--quiet"], sandbox)

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=sandbox,
        input="\0".join(tracked).encode(),
        capture_output=True,
        check=False,
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
        "src/giljo_mcp/downloads/__init__.py",
        "src/giljo_mcp/downloads/token_manager.py",
    ],
)
def test_known_silent_strip_victims_still_tracked(must_survive: str) -> None:
    tracked = set(_git(["ls-files"], REPO_ROOT).splitlines())
    assert must_survive in tracked, (
        f"{must_survive} is missing from `git ls-files`. This file was the "
        f"victim of the 2026-05-28 silent-strip bug and must remain tracked."
    )
