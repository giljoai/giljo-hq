# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_DIRS = (
    "frontend/src",
    "api/endpoints",
    "src/giljo_mcp/services",
    "src/giljo_mcp/tools",
    "src/giljo_mcp/models",
)

SCANNED_SUFFIXES = {".py", ".vue", ".js", ".ts", ".jsx", ".tsx"}

FORBIDDEN = re.compile(r"due_date|due_before|dueDate")


def _hits_under(relative_dir: str) -> list[str]:
    root = REPO_ROOT / relative_dir
    if not root.is_dir():
        return []
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN.search(line):
                found.append(f"  {path.relative_to(REPO_ROOT).as_posix()}:{lineno}: {line.strip()}")
    return found


def test_no_due_date_on_any_reader_surface() -> None:
    hits: list[str] = []
    for relative_dir in SCANNED_DIRS:
        hits.extend(_hits_under(relative_dir))

    assert not hits, (
        "The task due date is back on a reader surface or in the schema:\n"
        + "\n".join(hits)
        + "\n\nFE-9636 removed this field end to end because it rendered nowhere -- the "
        "TasksTable slot that displayed it had no matching header key, so no user ever "
        "saw a due date. If a due date is genuinely wanted again, it needs a column in "
        "the table headers and a decision about the tool-surface characters it costs, "
        "not a quiet re-add here."
    )


def test_the_scan_can_actually_fire(tmp_path: Path) -> None:
    assert FORBIDDEN.search("due_date: datetime | None = Field(None)")
    assert FORBIDDEN.search('kwargs["due_before"] = due_before')
    assert FORBIDDEN.search('<template #item.due_date="{ item }">')
    assert not FORBIDDEN.search("created_at = Column(DateTime(timezone=True))")

    for relative_dir in SCANNED_DIRS:
        assert (REPO_ROOT / relative_dir).is_dir(), f"{relative_dir} is not a directory -- the scan would silently pass"
    scanned = [p for p in (REPO_ROOT / "api/endpoints").rglob("*") if p.is_file() and p.suffix in SCANNED_SUFFIXES]
    assert scanned, "the suffix filter matched no files under api/endpoints"
