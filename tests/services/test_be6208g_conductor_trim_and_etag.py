# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.schemas.responses.orchestration import MissionResponse
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol


_WORKER_SPAWN_MARKERS = (
    "**COORDINATION ACTIONS (use as needed within the loop):**",
    "**Spawn a replacement agent:**",
    "**Spawn verification agent (after all deliverable agents complete):**",
    "**Implementation-phase verification spawning:**",
)


def _proto(*, is_chain_conductor: bool) -> str:
    return _generate_orchestrator_protocol(
        job_id="job-6208g",
        tenant_key="tk_6208g",
        executor_id="exec-6208g",
        execution_mode="multi_terminal",
        tool="multi_terminal",
        is_chain_conductor=is_chain_conductor,
    )




def test_conductor_protocol_omits_worker_spawn_block() -> None:
    conductor = _proto(is_chain_conductor=True)
    for marker in _WORKER_SPAWN_MARKERS:
        assert marker not in conductor, f"conductor protocol must NOT carry worker-spawn marker: {marker!r}"
    assert "**COORDINATION ACTIONS (chain conductor):**" in conductor, "conductor must get the trimmed note"
    assert "**PROGRESS REPORTING (MANDATORY after every coordination action):**" in conductor
    assert "### PHASE 3 — CLOSEOUT" not in conductor
    assert "### CHAIN FINALE (chain conductor" in conductor
    assert "## ORCHESTRATOR CONSTRAINTS" in conductor


def test_suborch_and_solo_keep_worker_spawn_block() -> None:
    non_conductor = _proto(is_chain_conductor=False)
    for marker in _WORKER_SPAWN_MARKERS:
        assert marker in non_conductor, f"non-conductor protocol MUST carry worker-spawn marker: {marker!r}"
    assert "**COORDINATION ACTIONS (chain conductor):**" not in non_conductor, (
        "the conductor-only trimmed note must never leak into a non-conductor protocol"
    )


def test_trim_is_the_only_body_difference() -> None:
    from giljo_mcp.services.protocol_sections.agent_lifecycle import (
        _CONDUCTOR_CLOSEOUT_NOTE,
        _CONDUCTOR_COORDINATION_NOTE,
        _ORCHESTRATOR_CONSTRAINTS_ANCHOR,
        _PHASE3_CLOSEOUT_START,
        _PROGRESS_REPORTING_ANCHOR,
        _WORKER_SPAWN_BLOCK_START,
    )
    from giljo_mcp.services.protocol_sections.orchestrator_body import (
        _GIT_CONSTRAINT_CONDUCTOR,
        _GIT_CONSTRAINT_SELF_ADOPT,
    )

    non_conductor = _proto(is_chain_conductor=False)
    conductor = _proto(is_chain_conductor=True)

    ws_start = non_conductor.find(_WORKER_SPAWN_BLOCK_START)
    ws_end = non_conductor.find(_PROGRESS_REPORTING_ANCHOR)
    assert ws_start != -1 and ws_end != -1 and ws_start < ws_end
    worker_block = non_conductor[ws_start:ws_end]

    fin_start = non_conductor.find(_PHASE3_CLOSEOUT_START)
    fin_end = non_conductor.find(_ORCHESTRATOR_CONSTRAINTS_ANCHOR)
    assert fin_start != -1 and fin_end != -1 and fin_start < fin_end
    finale_block = non_conductor[fin_start:fin_end]

    restored = conductor.replace(_CONDUCTOR_COORDINATION_NOTE, worker_block, 1)
    restored = restored.replace(_CONDUCTOR_CLOSEOUT_NOTE, finale_block, 1)
    restored = restored.replace(_GIT_CONSTRAINT_CONDUCTOR, _GIT_CONSTRAINT_SELF_ADOPT, 1)
    anchor = "## Orchestrator Coordination Protocol (3 Phases)"
    assert restored[restored.find(anchor) :] == non_conductor[non_conductor.find(anchor) :], (
        "conductor trims must remove ONLY the worker-spawn + PHASE-3 finale blocks "
        "and swap the role-scoped git bullet; the rest of the body is byte-identical"
    )
    assert _PHASE3_CLOSEOUT_START in non_conductor, "the PHASE-3 finale must remain in the non-conductor body"



_LEGACY_KEYS = {
    "job_id",
    "agent_id",
    "agent_name",
    "agent_display_name",
    "agent_identity",
    "mission",
    "project_id",
    "parent_job_id",
    "status",
    "created_at",
    "started_at",
    "thin_client",
    "full_protocol",
    "current_team_state",
    "project_phase",
    "blocked",
    "error",
    "user_instruction",
    "protocol_etag",
}


def test_mission_response_emits_etag_and_omits_unchanged_by_default() -> None:
    resp = MissionResponse(job_id="j1", agent_identity="ID", full_protocol="PROTO", protocol_etag="abc123")
    dumped = resp.model_dump(mode="json")
    assert set(dumped.keys()) == _LEGACY_KEYS, f"unexpected wire keys: {set(dumped) ^ _LEGACY_KEYS}"
    assert dumped["protocol_etag"] == "abc123"
    assert "protocol_unchanged" not in dumped


def test_mission_response_includes_cache_signal_when_set() -> None:
    resp = MissionResponse(
        job_id="j1",
        agent_identity=None,
        full_protocol=None,
        protocol_etag="deadbeef",
        protocol_unchanged=True,
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["protocol_etag"] == "deadbeef"
    assert dumped["protocol_unchanged"] is True
    assert dumped["agent_identity"] is None
    assert dumped["full_protocol"] is None


def test_mission_response_etag_present_without_match() -> None:
    resp = MissionResponse(
        job_id="j1",
        agent_identity="ID",
        full_protocol="PROTO",
        protocol_etag="freshhash",
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["protocol_etag"] == "freshhash"
    assert "protocol_unchanged" not in dumped, "False protocol_unchanged is stripped from the wire"
    assert dumped["full_protocol"] == "PROTO"


def test_compute_protocol_etag_is_stable_and_collision_resistant() -> None:
    a = MissionService._compute_protocol_etag("ID", "PROTO")
    b = MissionService._compute_protocol_etag("ID", "PROTO")
    assert a == b, "etag must be deterministic"

    assert MissionService._compute_protocol_etag("AB", "C") != MissionService._compute_protocol_etag("A", "BC")

    assert MissionService._compute_protocol_etag(None, None) != MissionService._compute_protocol_etag("ID", "PROTO")
