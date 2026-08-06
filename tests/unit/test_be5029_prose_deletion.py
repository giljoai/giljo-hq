# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Deletion gate for the BE-5029 prose contract (FE-5017 Phase C).

The deprecated ``user_approval_required`` boolean was the prose-only HITL
contract that BE-5029 replaced with the structured ``user_approvals`` primitive
plus the ``awaiting_user`` agent status. This test fails CI if any active
source, API, test, or frontend file reintroduces the dead string outside the
allowed survivors.

Allowed survivors (audit / historical / migration):
- private handover archives -- archived comms logs and historical session state
- ``docs/`` -- audit snapshots and the BE-5029a deletion list itself
- ``migrations/`` -- migration docstrings (historical record)
- ``src/giljo_mcp/models/user_approval.py`` -- model docstring referencing
  the prose contract being replaced (audit-of-why-this-model-exists)
- ``api/endpoints/mcp_tools/_message_tools.py`` -- ``request_approval`` tool
  description string ("Replaces the prose user_approval_required boolean.") --
  accurate marketing text inside the structured tool that displaced the prose
  (moved here from mcp_sdk_server.py in the BE-6042d wrapper split)
- ``tests/unit/test_be5029_prose_deletion.py`` -- this file
"""

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
        # Model docstring records why the model exists
        Path("src/giljo_mcp/models/user_approval.py"),
        # Tool description for request_approval references the displaced contract
        Path("api/endpoints/mcp_tools/_message_tools.py"),
        # This deletion test itself
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
    """``user_approval_required`` must not appear in active code outside survivors."""
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
    """Guard against drift: if a survivor file is moved/deleted, update the allowlist."""
    assert (REPO_ROOT / survivor).exists(), (
        f"Allowed-survivor {survivor} no longer exists. Update ALLOWED_SURVIVORS in this test."
    )
