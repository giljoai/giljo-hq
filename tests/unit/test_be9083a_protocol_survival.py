# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.protocol_survival import (
    PROTOCOL_END_MARKER,
    build_truncation_check,
    compute_next_required_actions,
)


def _cell(**kwargs) -> list[str]:
    result = compute_next_required_actions(**kwargs)
    assert result is not None
    return result


def _all_cells() -> dict[str, list[str]]:
    return {
        "worker": _cell(job_type="implementer", phase=None),
        "conductor": _cell(job_type="orchestrator", phase="implementation", is_chain_conductor=True),
        "chain_suborch_staging": _cell(job_type="orchestrator", phase="staging", is_chain_member=True),
        "chain_suborch_impl": _cell(job_type="orchestrator", phase="implementation", is_chain_member=True),
        "solo_staging": _cell(job_type="orchestrator", phase="staging"),
        "solo_impl": _cell(job_type="orchestrator", phase="implementation"),
    }


def test_every_cell_is_numbered_and_within_budget() -> None:
    for name, checklist in _all_cells().items():
        assert 1 <= len(checklist) <= 15, f"{name}: {len(checklist)} entries"
        for i, item in enumerate(checklist, start=1):
            assert item.startswith(f"{i}. "), f"{name} item {i} is not numbered: {item[:40]!r}"


def test_cells_are_distinct_and_carry_their_signature_steps() -> None:
    cells = _all_cells()

    worker = "\n".join(cells["worker"])
    assert "report_progress" in worker
    assert "complete_job" in worker
    assert "write_project_closeout" not in worker, "a worker must never be steered to closeout tools"

    conductor = "\n".join(cells["conductor"])
    assert "ready_to_advance" in conductor
    assert "spawn" in conductor.lower()
    assert "update_project_mission" not in conductor, "the conductor owns no project mission"

    suborch_staging = "\n".join(cells["chain_suborch_staging"])
    assert "update_project_mission" in suborch_staging
    assert "INERT" in suborch_staging
    assert "protocol_etag" in suborch_staging
    assert "get_job_mission" in suborch_staging
    assert "Implement" not in suborch_staging, "chain mode has no human Implement gate"

    suborch_impl = "\n".join(cells["chain_suborch_impl"])
    assert "write_project_closeout" in suborch_impl
    assert "Hub" in suborch_impl
    assert suborch_impl.index("complete_job") < suborch_impl.index("write_project_closeout"), (
        "the closeout order (complete_job FIRST) is load-bearing — the inverse raises COMPLETION_BLOCKED"
    )

    solo_staging = "\n".join(cells["solo_staging"])
    assert "Implement" in solo_staging, "solo staging ends at the human Implement gate"
    assert "spawn_job" in solo_staging

    solo_impl = "\n".join(cells["solo_impl"])
    assert "write_project_closeout" in solo_impl
    assert "Hub" not in solo_impl, "solo has no chain Hub thread protocol"

    rendered = ["\n".join(c) for c in cells.values()]
    assert len(set(rendered)) == len(rendered)


def test_unresolvable_orchestrator_cells_return_none() -> None:
    assert compute_next_required_actions(job_type="orchestrator", phase=None) is None
    assert compute_next_required_actions(job_type="orchestrator", phase=None, is_chain_member=True) is None
    assert compute_next_required_actions(job_type="orchestrator", phase="weird") is None


@pytest.mark.parametrize("job_type", ["implementer", "tester", "reviewer", "documenter", None, ""])
def test_every_non_orchestrator_job_type_gets_the_worker_cell(job_type) -> None:
    assert compute_next_required_actions(job_type=job_type, phase=None) == _cell(job_type="implementer", phase=None)


def test_conductor_wins_over_chain_member_flag() -> None:
    both = compute_next_required_actions(
        job_type="orchestrator", phase="implementation", is_chain_member=True, is_chain_conductor=True
    )
    assert both == _cell(job_type="orchestrator", phase="implementation", is_chain_conductor=True)


def test_truncation_check_names_marker_size_and_real_recovery() -> None:
    text = build_truncation_check(41_234)
    assert "~41234 chars" in text
    assert PROTOCOL_END_MARKER in text
    assert "protocol_etag" in text
    assert "section=" in text
    assert "protocol_toc" in text
    assert "ships later" not in text
