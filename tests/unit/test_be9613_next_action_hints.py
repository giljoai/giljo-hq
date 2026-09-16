# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest

from giljo_mcp.services import next_action as na


ALL_HINTS = (
    na.PROJECT_NOT_STAGED_HINT,
    na.PROJECT_AWAITING_GO_HINT,
    na.PROJECT_IN_FLIGHT_HINT,
    na.PROJECT_AWAITING_USER_HINT,
    na.PROJECT_PARKED_HINT,
    na.TASK_OPEN_HINT,
)

WIRED_READ_PATHS = (
    "src/giljo_mcp/tools/context_tools/get_project.py",
    "src/giljo_mcp/tools/context_tools/get_tasks.py",
    "src/giljo_mcp/services/project_service/_mcp_adapter_query_mixin.py",
    "src/giljo_mcp/services/diagnose_staging_hints.py",
    "src/giljo_mcp/services/workflow_status_service.py",
    "src/giljo_mcp/services/task_service/_mcp_adapter_mixin.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]




def test_not_staged_project_is_told_to_stage():
    hint = na.project_next_action(status="inactive", staging_status=None, implementation_launched_at=None)
    assert hint == {
        "tool": "stage_project",
        "args_hint": None,
        "why": (
            "To implement this project, call stage_project(project_id, mode). The server pauses "
            "you at staging for the user's go; then launch_implementation."
        ),
    }


@pytest.mark.parametrize("staging_status", ["staging", "staged"])
def test_mid_staging_lands_in_the_stage_project_bucket(staging_status):
    hint = na.project_next_action(status="inactive", staging_status=staging_status, implementation_launched_at=None)
    assert hint["tool"] == "stage_project"


def test_staged_project_is_told_to_wait_for_the_go():
    hint = na.project_next_action(status="inactive", staging_status="staging_complete", implementation_launched_at=None)
    assert hint == {
        "tool": "launch_implementation",
        "args_hint": None,
        "why": "Staging is complete. Wait for the user's go, then call launch_implementation(project_id).",
    }


def test_launched_project_is_told_to_report_and_close_out():
    hint = na.project_next_action(
        status="active", staging_status="staging_complete", implementation_launched_at="2026-09-16T00:00:00Z"
    )
    assert hint == {
        "tool": "report_progress",
        "args_hint": None,
        "why": "Implementation is in flight. Report with report_progress; finish with write_project_closeout.",
    }


def test_awaiting_user_wins_over_the_in_flight_hint():
    hint = na.project_next_action(
        status="active",
        staging_status="staging_complete",
        implementation_launched_at="2026-09-16T00:00:00Z",
        awaiting_user=True,
    )
    assert hint == {
        "tool": None,
        "args_hint": None,
        "why": "Blocked on a user decision. The user decides in the dashboard closeout modal or via decide_approval.",
    }


def test_parked_project_says_ask_before_un_parking():
    hint = na.project_next_action(status="parked", staging_status=None, implementation_launched_at=None)
    assert hint == {
        "tool": None,
        "args_hint": None,
        "why": "Parked by the user. Do not start work; ask before un-parking (update_project status='inactive').",
    }


@pytest.mark.parametrize("status", ["completed", "cancelled", "superseded", "terminated", "deleted"])
def test_terminal_project_gets_no_hint(status):
    assert (
        na.project_next_action(
            status=status, staging_status="staging_complete", implementation_launched_at="2026-09-16T00:00:00Z"
        )
        is None
    )


def test_parked_outranks_the_terminal_check_only_for_parked():
    assert na.project_next_action(status="parked", staging_status=None, implementation_launched_at=None) is not None




@pytest.mark.parametrize("statuses", [["pending"], ["in_progress"], ["completed", "pending"]])
def test_a_page_holding_an_open_task_gets_the_task_hint(statuses):
    assert na.task_list_next_action(statuses) == {
        "tool": "update_task",
        "args_hint": None,
        "why": (
            "Tasks are single-step. Do the work, then update_task(task_id, status='completed'). "
            "If it grows into multi-step work, create_project instead."
        ),
    }


@pytest.mark.parametrize("statuses", [[], ["completed"], ["cancelled", "completed"]])
def test_a_page_with_no_open_task_gets_no_hint(statuses):
    assert na.task_list_next_action(statuses) is None


def test_task_hint_accepts_a_generator_without_consuming_the_caller_rows():
    assert na.task_list_next_action(s for s in ["completed", "in_progress"]) is not None




@pytest.mark.parametrize(
    "hint",
    [
        na.project_next_action(status="inactive", staging_status=None, implementation_launched_at=None),
        na.project_next_action(status="parked", staging_status=None, implementation_launched_at=None),
        na.task_list_next_action(["pending"]),
    ],
)
def test_every_hint_is_the_canonical_be8003a_envelope(hint):
    assert set(hint) == {"tool", "args_hint", "why"}
    assert hint["args_hint"] is None
    assert hint["why"] and hint["why"].strip() == hint["why"]


@pytest.mark.parametrize("hint_text", ALL_HINTS)
def test_no_hint_is_multi_sentence_prose(hint_text):
    assert len(hint_text) <= 200
    assert "\n" not in hint_text




def _unwrapped(path: Path) -> str:
    return re.sub(r"[\"']\s*\n\s*[\"']", "", path.read_text(encoding="utf-8"))


def _shipped_python_sources() -> list[Path]:
    files: list[Path] = []
    for root in ("src", "api"):
        files.extend(p for p in (_REPO_ROOT / root).rglob("*.py") if "__pycache__" not in p.parts)
    return files


@pytest.mark.parametrize("hint_text", ALL_HINTS)
def test_each_hint_literal_lives_only_in_the_owning_module(hint_text):
    owner = _REPO_ROOT / "src" / "giljo_mcp" / "services" / "next_action.py"
    holders = [p for p in _shipped_python_sources() if hint_text in _unwrapped(p)]
    assert holders == [owner], f"hint wording duplicated outside next_action.py: {[str(p) for p in holders]}"


@pytest.mark.parametrize("read_path", WIRED_READ_PATHS)
def test_every_wired_read_path_imports_the_owning_module(read_path):
    source = (_REPO_ROOT / read_path).read_text(encoding="utf-8")
    assert "from giljo_mcp.services.next_action import" in source, f"{read_path} no longer sources its hint wording"
