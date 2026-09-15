# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path

import pytest


PROSE_TOKEN = "user_approval_required"

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = (
    "src",
    "api",
    "tests",
    "frontend/src",
    "frontend/tests",
)

ALLOWED_SURVIVORS = frozenset(
    {
        Path("src/giljo_mcp/models/user_approval.py"),
        Path("api/endpoints/mcp_tools/_message_tools.py"),
        Path("tests/unit/test_be5029_prose_deletion.py"),
    }
)

SCAN_EXTENSIONS = frozenset({".py", ".js", ".vue", ".ts", ".tsx", ".jsx"})


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for top in SCAN_DIRS:
        base = REPO_ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SCAN_EXTENSIONS:
                continue
            if "node_modules" in path.parts or ".venv" in path.parts:
                continue
            files.append(path)
    return files


def test_user_approval_required_prose_deleted():
    offenders: list[str] = []
    for path in _iter_scan_files():
        rel = path.relative_to(REPO_ROOT)
        if rel in ALLOWED_SURVIVORS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if PROSE_TOKEN in text:
            offenders.append(str(rel).replace("\\", "/"))

    assert not offenders, (
        f"Forbidden token {PROSE_TOKEN!r} reintroduced in active code. "
        f"BE-5029 deleted this prose contract; use request_approval + "
        f"awaiting_user instead. Offenders: {offenders}"
    )


@pytest.mark.parametrize("survivor", sorted(ALLOWED_SURVIVORS))
def test_allowed_survivors_still_exist(survivor: Path):
    assert (REPO_ROOT / survivor).exists(), (
        f"Allowed-survivor {survivor} no longer exists. Update ALLOWED_SURVIVORS in this test."
    )
