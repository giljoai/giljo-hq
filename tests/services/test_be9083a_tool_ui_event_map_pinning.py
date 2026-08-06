# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9083a — pinning test for the TOOL_UI_EVENT_MAP reference doc.

The map is the source of truth for BE-9083b's lifecycle breadcrumb prose, so it must
never silently drift from the emitting code. Contract pinned here, row by row:

  * every Emitter path in the table exists in the repo;
  * every named WS event string literally appears in its Emitter's source
    (an emitter rename/removal breaks the row and this test);
  * the tools the BE-9083a scope names all have at least one row.

Pure file-reading assertions — no DB, no module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "handovers" / "Reference_docs" / "TOOL_UI_EVENT_MAP.md"

# The pinned doc is a private reference doc, stripped from the CE export (both
# .export-exclude and the export scripts' STRIP_DIRS). Private CI keeps the doc,
# so these assertions still run and enforce there; a CE self-hoster running the
# full suite skips green instead of hard-failing on the absent file. Mirrors
# tests/unit/test_requirements_lock_drift.py's CI-only-artifact skip.
pytestmark = pytest.mark.skipif(
    not _DOC.exists(),
    reason="TOOL_UI_EVENT_MAP.md is a private reference doc, stripped from the CE export; pinned on private CI only.",
)

# Tools the BE-9083a scope requires the map to cover.
_REQUIRED_TOOLS = {
    "complete_job",
    "spawn_job",
    "report_progress",
    "set_agent_status",
    "close_job",
    "update_project_mission",
    "request_approval",
    "post_to_thread",
    "stage_project",
    "write_project_closeout",
    "start_chain_run",
}


def _rows() -> list[dict[str, str]]:
    """Parse the map's markdown table into row dicts (Tool/Phase/Event/Emitter/UI)."""
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, str]] = []
    in_table = False
    for line in lines:
        if line.startswith("| Tool |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            if re.match(r"^\|[-\s|]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 5:
                raise AssertionError(f"malformed map row (expected 5 cells): {line!r}")
            rows.append({"tool": cells[0], "phase": cells[1], "event": cells[2], "emitter": cells[3], "ui": cells[4]})
    assert rows, "no table rows parsed from TOOL_UI_EVENT_MAP.md"
    return rows


def test_doc_exists_and_covers_the_required_tools() -> None:
    assert _DOC.exists(), f"missing {_DOC}"
    tools = {re.sub(r"\s*\(.*", "", r["tool"]) for r in _rows()}
    missing = _REQUIRED_TOOLS - tools
    assert not missing, f"TOOL_UI_EVENT_MAP.md is missing required tool rows: {sorted(missing)}"


def test_every_row_pins_to_a_real_emitter() -> None:
    for row in _rows():
        emitter = _REPO_ROOT / row["emitter"]
        assert emitter.exists(), f"{row['tool']}: emitter file does not exist: {row['emitter']}"


def test_every_event_string_appears_in_its_emitter_source() -> None:
    """The load-bearing pin: the event name in each row must literally appear in the
    named emitter file. A '—' event row (no WS emit) asserts the OPPOSITE — the file
    must not contain a broadcast_to_tenant call at all is too strong, so it only pins
    file existence (covered above)."""
    for row in _rows():
        event = row["event"]
        if event.startswith("—"):
            continue
        source = (_REPO_ROOT / row["emitter"]).read_text(encoding="utf-8")
        assert event in source, (
            f"{row['tool']} ({row['phase']}): event {event!r} not found in {row['emitter']} — "
            "the emitter moved or was renamed; update TOOL_UI_EVENT_MAP.md in the same change"
        )


def test_be9332_stage_project_row_pins_the_prompt_generated_emit() -> None:
    """BE-9332: the stage_project row used to be an explicit NON-emit row ('— (no direct
    WS emit on the MCP tool path)'), and it also mis-named the REST staging endpoint's
    event as ``agent:created``. Both were wrong once the MCP path started emitting.

    This pins the corrected row so it cannot silently revert to a non-emit row if the
    broadcast is ever dropped from ``ProjectToolsMixin.stage_project`` — the generic
    row-level assertions above skip '—' rows, so without this a regression would simply
    stop being checked instead of failing.
    """
    rows = [r for r in _rows() if r["tool"] == "stage_project"]
    assert rows, "TOOL_UI_EVENT_MAP.md lost its stage_project row"
    assert any(r["event"] == "orchestrator:prompt_generated" for r in rows), (
        "the stage_project row must record the orchestrator:prompt_generated emit (BE-9332); "
        f"got events: {[r['event'] for r in rows]}"
    )

    # A CALL to the emit must still exist in the MCP tool itself, not merely in the doc.
    # Assert the awaited call, not the bare name: the name alone is satisfied by the
    # import statement, so a deleted call site with a leftover import would slip past.
    # This is a cheap source-level pin only — the behavioural guarantee lives in
    # tests/integration/test_inf6049b_stage_implement_tools.py, which drives the real
    # transport and is what actually proves the event reaches the wire.
    tool_src = (_REPO_ROOT / "src/giljo_mcp/tools/tool_accessor/_project_tools.py").read_text(encoding="utf-8")
    assert "await broadcast_orchestrator_prompt_generated(" in tool_src, (
        "stage_project no longer calls the shared orchestrator-prompt emitter — "
        "the CLI-driven staging path has gone silent again (BE-9332)"
    )


def test_ce0032_staging_end_waiting_row_is_present() -> None:
    """CE-0032: the staging_end branch keeps the orchestrator ALIVE in status
    'waiting' (not complete). The map must state that, and the code must still
    implement it (execution.status = 'waiting' in the completion status applier)."""
    rows = [r for r in _rows() if r["tool"] == "complete_job" and "staging_end" in r["phase"]]
    assert any('"waiting"' in r["ui"] or "waiting" in r["ui"] for r in rows), (
        "the staging_end row must document the CE-0032 status='waiting' broadcast"
    )
    completion_src = (_REPO_ROOT / "src/giljo_mcp/services/job_completion_service.py").read_text(encoding="utf-8")
    assert 'execution.status = "waiting"' in completion_src, (
        "CE-0032 staging_end waiting-status code moved — re-verify the map row"
    )
