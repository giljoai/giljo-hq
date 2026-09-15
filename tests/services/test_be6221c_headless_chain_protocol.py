# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_chain_drive,
    _build_ch_sub_orchestrator,
)
from giljo_mcp.services.protocol_sections.orchestrator_body import trim_embedded_protocol_for_chain
from giljo_mcp.tools.giljo_guide import build_giljo_guide
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_MODE = "multi_terminal"


def _suborch(execution_mode: str = _MODE, *, chain_mission: str | None = None) -> str:
    return _build_ch_sub_orchestrator(
        run_id="run-6221c",
        position=2,
        n_projects=3,
        execution_mode=execution_mode,
        chain_mission=chain_mission,
    )


def _chain_drive() -> str:
    return _build_ch_chain_drive(
        run_id="run-6221c",
        resolved_order=["p1", "p2", "p3"],
        current_index=0,
        execution_mode=_MODE,
        conductor_agent_id="cond-6221c",
        job_id="job-6221c",
    )




def test_guide_carries_headless_chain_drive_recipe() -> None:
    guide = build_giljo_guide()["guide"]
    assert "link_projects" in guide, "guide must name the headless chain entry point"
    low = guide.lower()
    for verb in ("run", "link", "join", "chain"):
        assert verb in low, f"intent-routing verb {verb!r} must appear in the guide"
    assert "execution_mode" in guide and "subagent" in guide and "multi_terminal" in guide
    assert "conductor" in low
    assert "get_staging_instructions" in guide
    assert "ready_to_advance" in guide
    assert "list_projects" in guide
    assert "CONDUCTOR" in guide


def test_guide_chain_recipe_carries_stage_halt_go_drive_sequence() -> None:
    guide = build_giljo_guide()["guide"]
    low = guide.lower()
    i_end = low.find("complete_job to end staging")
    i_wait = low.find("explicit go")
    i_after = low.find("after the user says go")
    i_drive = low.find("ready_to_advance")
    assert i_end != -1, "recipe must still end staging with complete_job"
    assert i_wait != -1, "recipe must require the user's explicit GO"
    assert i_after != -1, "recipe must proceed only after the user says go"
    assert i_drive != -1, "recipe must still drive on the ready_to_advance gate"
    assert i_end < i_wait < i_after < i_drive, (
        "the recipe beats must be ordered: end staging -> wait for GO -> after GO -> drive"
    )
    assert "do not drive yet" in low, "the recipe must say not to drive before the GO"
    assert "implement chain" in low, "the dashboard GO equivalent must be named"


@pytest.mark.asyncio
async def test_guide_headless_chain_recipe_surfaces_over_transport() -> None:
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_giljo_guide", {})
    assert result.is_error is False, f"get_giljo_guide errored at the transport boundary: {result}"
    guide = json.loads(result.content[0].text)["guide"]
    assert "link_projects" in guide
    assert "get_staging_instructions" in guide
    assert "ready_to_advance" in guide




def test_suborch_bootstrap_lists_hub_thread_tools() -> None:
    body = _suborch()
    assert "TOOLSEARCH BOOTSTRAP" in body, "the chapter must carry an explicit bootstrap directive"
    for tool in ("join_thread", "post_to_thread", "get_thread_history"):
        assert tool in body, f"Hub tool {tool!r} must be in the sub-orch bootstrap query"
    low = body.lower()
    assert "first toolsearch" in low
    assert "second toolsearch" in low or "round-trip" in low


def test_suborch_bootstrap_is_mode_agnostic() -> None:
    mt = _suborch("multi_terminal")
    cli = _suborch("claude_code_cli")
    for tool in ("join_thread", "post_to_thread", "get_thread_history"):
        assert tool in mt and tool in cli




def test_suborch_states_workers_inert_explicitly() -> None:
    body = _suborch()
    flat = " ".join(body.split())
    assert "INERT" in body
    assert "do NOT launch them before that gate" in flat
    assert "RE-POLL" in body
    assert "no human gate" in flat


def test_suborch_workers_inert_note_is_mode_agnostic_byte_identical() -> None:

    def _note(text: str) -> str:
        start = text.find("NOTE (workers-inert)")
        end = text.find("4. END STAGING")
        assert start != -1 and end != -1 and start < end
        return text[start:end]

    assert _note(_suborch("multi_terminal")) == _note(_suborch("claude_code_cli"))


def test_chain_worker_block_message_is_chain_aware() -> None:
    from giljo_mcp.services.mission_service import _CHAIN_WORKER_STAGING_BLOCK_MESSAGE

    msg = _CHAIN_WORKER_STAGING_BLOCK_MESSAGE
    assert "click the 'Implement'" not in msg and "must click" not in msg
    assert "get_job_mission" in msg and "no human gate" in msg




def test_chain_drive_blesses_background_self_wake_pattern() -> None:
    chapter = _chain_drive()
    low = chapter.lower()
    assert "sleep 1 60" in chapter, "must give the concrete `sleep 1 N` self-wake command"
    assert "only inspects the first" in low or "inspects only the first" in low, (
        "must explain the sleep-1-N workaround (harness inspects only the first arg)"
    )
    assert "does not re-invoke" in low or "not re-invoke you" in low, (
        "must warn set_agent_status(sleeping) does not re-invoke the conductor"
    )
    assert "dashboard label" in low
    assert "stall" in low, "must warn that sleeping-and-stopping stalls the chain"



_NEW_CHAIN_ONLY_STRINGS = (
    "do NOT launch them before that gate",
    "ADD join_thread, post_to_thread",
    "NOTE (workers-inert)",
)


def test_new_chain_strings_absent_from_solo_render() -> None:
    solo = _generate_orchestrator_protocol(
        job_id="job-solo",
        tenant_key="tk_solo",
        executor_id="exec-solo",
        execution_mode=_MODE,
        tool=_MODE,
        is_chain_conductor=False,
    )
    for needle in _NEW_CHAIN_ONLY_STRINGS:
        assert needle not in solo, f"chain-only string leaked into the solo render: {needle!r}"


def test_suborch_render_stays_within_be6214_band() -> None:
    solo = _generate_orchestrator_protocol(
        job_id="job-6214",
        tenant_key="tk_6214",
        executor_id="exec-6214",
        execution_mode=_MODE,
        tool=_MODE,
        is_chain_conductor=False,
    )
    render = "\n\n".join([trim_embedded_protocol_for_chain(solo, "sub_orchestrator"), _suborch()])
    nbytes = len(render.encode("utf-8"))
    assert 20_000 <= nbytes <= 23_500, f"sub-orch render fell out of the BE-6214 band: {nbytes}"
