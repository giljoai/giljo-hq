# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "handovers" / "Reference_docs" / "TOOL_UI_EVENT_MAP.md"

pytestmark = pytest.mark.skipif(
    not _DOC.exists(),
    reason="TOOL_UI_EVENT_MAP.md is a private reference doc, stripped from the CE export; pinned on private CI only.",
)

_REQUIRED_TOOLS = {
    "complete_job",
    "spawn_job",
    "report_progress",
    "set_agent_status",
    "finalize_job",
    "update_project_mission",
    "request_approval",
    "post_to_thread",
    "stage_project",
    "write_project_closeout",
    "link_projects",
}


def _rows() -> list[dict[str, str]]:
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
    rows = [r for r in _rows() if r["tool"] == "stage_project"]
    assert rows, "TOOL_UI_EVENT_MAP.md lost its stage_project row"
    assert any(r["event"] == "orchestrator:prompt_generated" for r in rows), (
        "the stage_project row must record the orchestrator:prompt_generated emit (BE-9332); "
        f"got events: {[r['event'] for r in rows]}"
    )

    tool_src = (_REPO_ROOT / "src/giljo_mcp/tools/tool_accessor/_project_tools.py").read_text(encoding="utf-8")
    assert "await broadcast_orchestrator_prompt_generated(" in tool_src, (
        "stage_project no longer calls the shared orchestrator-prompt emitter — "
        "the CLI-driven staging path has gone silent again (BE-9332)"
    )


def test_ce0032_staging_end_waiting_row_is_present() -> None:
    rows = [r for r in _rows() if r["tool"] == "complete_job" and "staging_end" in r["phase"]]
    assert any('"waiting"' in r["ui"] or "waiting" in r["ui"] for r in rows), (
        "the staging_end row must document the CE-0032 status='waiting' broadcast"
    )
    completion_src = (_REPO_ROOT / "src/giljo_mcp/services/job_completion_service.py").read_text(encoding="utf-8")
    assert 'execution.status = "waiting"' in completion_src, (
        "CE-0032 staging_end waiting-status code moved — re-verify the map row"
    )
