# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.closeout_sequence import (
    CANONICAL_CLOSEOUT_STEPS,
    build_required_sequence,
)
from giljo_mcp.services.protocol_sections.worker_body import _build_worker_protocol_body
from giljo_mcp.tools.giljo_guide import build_giljo_guide


def _worker_protocol_sample() -> str:
    return _build_worker_protocol_body(
        job_id="JOB-TEST",
        tenant_key="tenant-test",
        executor_id="AGENT-TEST",
        job_type="implementer",
        phase1_step4="",
        git_commit_block="",
        giljo_block="",
        protocol_framing="",
        comm_thread_id="THREAD-TEST",
    )


class TestNoWriteMemoryEntryInClosoutSequence:

    def test_worker_protocol_never_prescribes_write_memory_entry_as_a_closeout_step(self):
        body = _worker_protocol_sample()
        assert "ORCHESTRATOR ADDENDUM" not in body
        assert "closeout step" not in body
        assert "write_memory_entry(...)                                    #" not in body

    def test_required_sequence_rejection_never_prescribes_write_memory_entry(self):
        steps = build_required_sequence("job-123")
        assert not any("write_memory_entry" in step for step in steps)

    def test_guide_states_write_memory_entry_is_redundant_for_closeout(self):
        guide = build_giljo_guide()["guide"]
        assert "REDUNDANT" in guide
        assert "write_project_closeout" in guide


class TestCanonicalSequenceConsistency:

    def test_required_sequence_matches_canonical_steps_in_order(self):
        steps = build_required_sequence("job-abc")
        assert len(steps) == len(CANONICAL_CLOSEOUT_STEPS)
        assert steps[0].startswith("1. complete_job(job_id='job-abc')")
        assert "write_project_closeout" in steps[-1]

    def test_guide_orders_complete_job_before_write_project_closeout(self):
        guide = build_giljo_guide()["guide"]
        complete_job_pos = guide.index("complete_job")
        closeout_pos = guide.rindex("`complete_job` -> `write_project_closeout`")
        assert complete_job_pos <= closeout_pos
        assert "`complete_job` -> `write_project_closeout`" in guide
