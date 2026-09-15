# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_sub_orchestrator
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    _SUBORCH_PHASE1_END,
    _SUBORCH_PHASE1_START,
    slice_chain_mission_for_position,
    trim_embedded_protocol_for_chain,
)


_MISSION_3 = (
    "### P_1 (aaaa):\n"
    "consumes = the repo baseline\n"
    "produces = endpoint_1.py\n"
    "must leave = ThingService.do_1 callable\n\n"
    "### P_2 (bbbb):\n"
    "consumes = output of P_1 upstream\n"
    "produces = endpoint_2.py\n"
    "must leave = migration ce_0002 idempotent\n\n"
    "### P_3 (cccc):\n"
    "consumes = output of P_2\n"
    "produces = endpoint_3.py\n"
    "must leave = router registered"
)




def test_slice_returns_only_own_block() -> None:
    sliced = slice_chain_mission_for_position(_MISSION_3, 2)
    assert sliced.startswith("### P_2 (bbbb):")
    assert "produces = endpoint_2.py" in sliced
    assert "P_1 (aaaa)" not in sliced
    assert "### P_3" not in sliced


def test_slice_first_and_last_positions() -> None:
    first = slice_chain_mission_for_position(_MISSION_3, 1)
    assert first.startswith("### P_1 (aaaa):")
    assert "### P_2" not in first
    last = slice_chain_mission_for_position(_MISSION_3, 3)
    assert last.startswith("### P_3 (cccc):")
    assert "must leave = router registered" in last


def test_slice_ignores_body_references_to_other_projects() -> None:
    first = slice_chain_mission_for_position(_MISSION_3, 1)
    assert (
        first
        == "### P_1 (aaaa):\nconsumes = the repo baseline\nproduces = endpoint_1.py\nmust leave = ThingService.do_1 callable"
    )


def test_slice_word_boundary_p2_not_p20() -> None:
    mission = "### P_2 (a):\nfoo\n\n### P_20 (b):\nbar"
    assert slice_chain_mission_for_position(mission, 2) == "### P_2 (a):\nfoo"
    assert slice_chain_mission_for_position(mission, 20) == "### P_20 (b):\nbar"




def test_slice_no_headers_ships_whole() -> None:
    freeform = "Do the thing. Consume the repo. Produce the endpoint. Leave it callable."
    assert slice_chain_mission_for_position(freeform, 2) == freeform


def test_slice_position_absent_ships_whole_and_warns(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        out = slice_chain_mission_for_position(_MISSION_3, 5)
    assert out == _MISSION_3
    assert any("position 5" in r.message for r in caplog.records)


def test_slice_empty_is_returned_as_is() -> None:
    assert slice_chain_mission_for_position("", 1) == ""




def test_suborch_chapter_inlines_only_its_slice() -> None:
    chapter = _build_ch_sub_orchestrator(
        run_id="run-9083c", position=2, n_projects=3, execution_mode="multi_terminal", chain_mission=_MISSION_3
    )
    assert "### P_2 (bbbb):" in chapter
    assert "produces = endpoint_2.py" in chapter
    assert "produces = endpoint_1.py" not in chapter
    assert "produces = endpoint_3.py" not in chapter
    assert "get_context" in chapter
    assert "CHAIN-MISSION SLICE (P_2" in chapter


def test_suborch_chapter_degenerate_mission_inlines_whole() -> None:
    freeform = "Freeform mission with no per-project headers at all."
    chapter = _build_ch_sub_orchestrator(
        run_id="run-9083c", position=1, n_projects=1, execution_mode="multi_terminal", chain_mission=freeform
    )
    assert freeform in chapter




def _solo_suborch() -> str:
    return _generate_orchestrator_protocol(
        job_id="j",
        tenant_key="t",
        executor_id="e",
        execution_mode="multi_terminal",
        tool="multi_terminal",
        is_chain_conductor=False,
    )


def test_phase1_trim_fires_and_removes_human_gate_seams() -> None:
    solo = _solo_suborch()
    trimmed = trim_embedded_protocol_for_chain(solo, "sub_orchestrator")
    assert len(trimmed) < len(solo)
    assert _SUBORCH_PHASE1_START in solo
    assert "Copy agent prompts from the dashboard to start them" not in trimmed
    assert "### PHASE 1 — STARTUP (chain sub-orchestrator)" in trimmed
    assert "CH_SUB_ORCHESTRATOR step 5" in trimmed


def test_phase1_trim_preserves_load_bearing_mechanics() -> None:
    trimmed = trim_embedded_protocol_for_chain(_solo_suborch(), "sub_orchestrator")
    assert "current_team_state" in trimmed
    assert "pre-planned coordination TODOs" in trimmed
    assert "### PHASE 2 — ACTIVE COORDINATION" in trimmed


def test_solo_render_is_untouched_by_the_new_trim() -> None:
    solo = _solo_suborch()
    assert _SUBORCH_PHASE1_START in solo
    assert _SUBORCH_PHASE1_END in solo




def test_heavy_tools_advertise_max_result_size_meta() -> None:
    import api.endpoints.mcp_tools  # noqa: F401 — registration side effect
    from api.endpoints.mcp_tools._base import MCP_MAX_RESULT_SIZE_CHARS, mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ("get_job_mission", "get_staging_instructions", "get_thread_history", "list_projects"):
        assert tools[name].meta == {"anthropic/maxResultSizeChars": MCP_MAX_RESULT_SIZE_CHARS}, name
    assert tools["spawn_job"].meta is None
