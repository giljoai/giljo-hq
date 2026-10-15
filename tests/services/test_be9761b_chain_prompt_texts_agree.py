# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.endpoints.chain_prompt_bootstrap import CHAIN_MEMBER_FALLBACK_PREAMBLE, _build_conductor_bootstrap
from giljo_mcp.platform_registry import get_preset
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
    _build_ch_chain_staging,
    _build_ch_sub_orchestrator,
)
from giljo_mcp.services.protocol_sections.orchestrator_body import CHAIN_DRIVER_MODEL, find_chain_mission_block


_JOB = "11111111-2222-3333-4444-555555555555"
_AGENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_RUN = "run-9761b"
_P1 = "c9ddba18-4473-44dc-97f2-f2abcb2b57c9"
_P2 = "3b4211de-838b-4b59-bc34-42bf75bdfd36"
_P3 = "0d0d0d0d-0000-0000-0000-000000000003"

_EM124_MISSION = (
    "CHAIN MISSION: worker briefing fixes\n\n"
    "Shared rules for every sub-orchestrator:\n- one committer per tree\n\n"
    f"### P1 ({_P1}) BE-9752 real dependencies\n"
    "consumes = master as merged\n"
    "produces = YOUR DEPENDENCIES built from predecessor links\n"
    "must leave = team_context.py signature unchanged\n\n"
    f"### P2 ({_P2}) BE-9753 git rule follows the mode\n"
    "consumes = P1 merged\n"
    "produces = worker git block per mode\n"
    "must leave = worker_body.py stable\n\n"
    f"### P3 ({_P3}) BE-9756 role text once\n"
    "consumes = P2 merged\n"
    "produces = agent_identity carries the role text\n"
    "must leave = master CI green"
)

_OLD_DRIVER_PHRASES = (
    "the user starts the next project when this one closes",
    "the conductor decides the next step",
)


def _member_bootstrap(phase: str) -> str:
    return _build_conductor_bootstrap(
        identity={"job_id": _JOB, "agent_id": _AGENT, "run_id": _RUN, "project_id": _P1},
        mcp_url="http://localhost:7272",
        phase=phase,
        harness_is_claude=True,
    )


def _suborch(phase: str | None, **kwargs) -> str:
    return _build_ch_sub_orchestrator(
        run_id=_RUN, position=1, n_projects=3, execution_mode="subagent", phase=phase, **kwargs
    )




def _driver_surfaces() -> dict[str, str]:
    return {
        "member bootstrap (staging)": _member_bootstrap("staging"),
        "member bootstrap (implementation)": _member_bootstrap("implementation"),
        "recovery prompt": f"{CHAIN_MEMBER_FALLBACK_PREAMBLE}\n\n{_member_bootstrap('staging')}",
        "CH_SUB_ORCHESTRATOR (staging)": _suborch(None, chain_mission=_EM124_MISSION, project_id=_P1),
        "CH_SUB_ORCHESTRATOR (implementation)": _suborch("implementation", staging_status="staging_complete"),
        "CH_CAPABILITY (cli)": _build_ch_capability("subagent"),
        "CH_CAPABILITY (shell-less)": _build_ch_capability("subagent", preset=get_preset("desktop_app")),
        "conductor staging (CH_CAPABILITY + CH_CHAIN_STAGING)": "\n\n".join(
            [
                _build_ch_capability("subagent"),
                _build_ch_chain_staging(
                    run_id=_RUN, resolved_order=[_P1, _P2, _P3], execution_mode="subagent", job_id=_JOB
                ),
            ]
        ),
        "conductor drive (CH_CAPABILITY + CH_CHAIN_DRIVE)": "\n\n".join(
            [
                _build_ch_capability("subagent"),
                _build_ch_chain_drive(
                    run_id=_RUN,
                    resolved_order=[_P1, _P2, _P3],
                    current_index=0,
                    execution_mode="subagent",
                    conductor_agent_id=_AGENT,
                    job_id=_JOB,
                ),
            ]
        ),
    }


@pytest.mark.parametrize("surface", list(_driver_surfaces()))
def test_every_chain_surface_states_the_one_driver_model(surface: str) -> None:
    text = " ".join(_driver_surfaces()[surface].split())
    assert CHAIN_DRIVER_MODEL in text, f"{surface} does not state the driver model"
    for old in _OLD_DRIVER_PHRASES:
        assert old not in text, f"{surface} still carries the contradicting phrase {old!r}"


def test_driver_model_names_server_user_conductor_and_recovery() -> None:
    assert "the server advances the chain" in CHAIN_DRIVER_MODEL
    assert "user" in CHAIN_DRIVER_MODEL and "conductor" in CHAIN_DRIVER_MODEL
    assert "never starts the next" in CHAIN_DRIVER_MODEL
    assert "recovery only" in CHAIN_DRIVER_MODEL


def test_chain_drive_no_longer_claims_index_advances_at_staging_end() -> None:
    drive = " ".join(_driver_surfaces()["conductor drive (CH_CAPABILITY + CH_CHAIN_DRIVE)"].split())
    assert "advances the run's current_index + marks P_i" not in drive




def test_member_staging_bootstrap_calls_get_job_mission_first() -> None:
    text = _member_bootstrap("staging")
    boot = text.find(f"get_job_mission(job_id='{_JOB}')")
    staging = text.find(f"get_staging_instructions(job_id='{_JOB}')")
    assert boot != -1, "the member bootstrap never calls get_job_mission"
    assert staging != -1, "the member bootstrap lost its get_staging_instructions call"
    assert boot < staging, "get_job_mission must come before get_staging_instructions"
    assert "CH_SUB_ORCHESTRATOR" in text[boot:staging], "the boot call must name the protocol it returns"


def test_conductor_staging_bootstrap_is_unchanged_in_order() -> None:
    text = _build_conductor_bootstrap(
        identity={"job_id": _JOB, "agent_id": _AGENT, "run_id": _RUN},
        mcp_url="http://localhost:7272",
        phase="staging",
        harness_is_claude=True,
    )
    assert "get_job_mission(job_id=" not in text
    assert f"get_staging_instructions(job_id='{_JOB}')" in text




def test_implementation_chapter_does_not_claim_a_staging_end_complete_job() -> None:
    text = " ".join(_suborch("implementation", staging_status="staging_complete").split())
    assert "ended staging (complete_job)" not in text
    assert "posted a staging-complete note" not in text
    assert "STAGING -- ALREADY COMPLETE" in text
    assert "staging_status: staging_complete" in text


def test_implementation_chapter_with_unrecorded_staging_says_so() -> None:
    text = " ".join(_suborch("implementation", staging_status="staged").split())
    assert "ALREADY COMPLETE" not in text
    assert "staging_status: staged" in text
    assert "has not recorded" in text


def test_implementation_chapter_with_unknown_staging_status_claims_nothing() -> None:
    text = " ".join(_suborch("implementation").split())
    assert "ALREADY COMPLETE" not in text
    assert "has not recorded" in text




@pytest.mark.parametrize(
    ("position", "project_id", "own", "others"),
    [
        (1, _P1, "BE-9752", ("BE-9753", "BE-9756")),
        (2, _P2, "BE-9753", ("BE-9752", "BE-9756")),
        (3, _P3, "BE-9756", ("BE-9752", "BE-9753")),
    ],
)
def test_em124_header_shape_slices_to_own_block(position, project_id, own, others) -> None:
    block = find_chain_mission_block(_EM124_MISSION, position, project_id)
    assert block is not None and own in block
    for other in others:
        assert other not in block
    assert "Shared rules" not in block


def test_block_found_by_project_id_when_numbering_differs() -> None:
    mission = f"## Step one ({_P2})\nproduces = x\n\n## Step two ({_P1})\nproduces = y"
    block = find_chain_mission_block(mission, 1, _P1)
    assert block is not None and "produces = y" in block and "produces = x" not in block


def test_canonical_p_underscore_header_still_slices() -> None:
    mission = "### P_1 (a):\nfoo\n\n### P_2 (b):\nbar\n\n### P_20 (c):\nbaz"
    assert find_chain_mission_block(mission, 2) == "### P_2 (b):\nbar"
    assert find_chain_mission_block(mission, 20) == "### P_20 (c):\nbaz"


@pytest.mark.parametrize("mission", ["", "Freeform mission, no headers at all.", "### P_2 (b):\nbar"])
def test_no_own_block_returns_none(mission: str) -> None:
    assert find_chain_mission_block(mission, 1, _P1) is None


def test_suborch_chapter_inlines_only_the_own_block_for_em124_shape() -> None:
    text = _suborch(None, chain_mission=_EM124_MISSION, project_id=_P1)
    assert "BE-9752 real dependencies" in text
    assert "BE-9753" not in text and "BE-9756" not in text
    assert "YOUR CHAIN-MISSION SLICE (P_1, live)" in text


def test_suborch_chapter_fallback_ships_whole_mission_and_says_so() -> None:
    freeform = "Freeform chain mission with no per-project headers."
    text = _suborch(None, chain_mission=freeform, project_id=_P1)
    assert freeform in text
    assert "YOUR CHAIN-MISSION SLICE" not in text
    assert "FULL CHAIN MISSION" in text
    assert "no contract block for this project" in " ".join(text.split())




def _conductor_protocol(mode: str) -> str:
    return " ".join(
        _generate_orchestrator_protocol(
            job_id=_JOB,
            tenant_key="tk_9761b",
            executor_id="exec-9761b",
            execution_mode=mode,
            tool="claude-code" if mode == "subagent" else mode,
            is_chain_conductor=True,
        ).split()
    )


def test_subagent_conductor_git_line_names_the_sub_orchestrator_as_committer() -> None:
    text = _conductor_protocol("subagent")
    assert "each project's own workers commit their work" not in text
    assert "sub-orchestrator commits once" in text


def test_multi_terminal_conductor_git_line_names_each_worker_as_committer() -> None:
    text = _conductor_protocol("multi_terminal")
    assert "each worker commits its own work in its own tree" in text
    assert "sub-orchestrator commits once" not in text
