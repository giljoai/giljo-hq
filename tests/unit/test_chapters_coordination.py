# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections import chapters_coordination, chapters_reference
from giljo_mcp.services.protocol_sections.chapters_coordination import (
    _build_ch_messaging,
    _build_ch_orchestrator_authority,
    _build_ch_team,
)


def test_builders_live_in_coordination_module() -> None:
    assert _build_ch_team.__module__ == chapters_coordination.__name__
    assert _build_ch_messaging.__module__ == chapters_coordination.__name__
    assert _build_ch_orchestrator_authority.__module__ == chapters_coordination.__name__


def test_builders_not_left_in_reference_module() -> None:
    for name in ("_build_ch_team", "_build_ch_messaging", "_build_ch_orchestrator_authority"):
        assert not hasattr(chapters_reference, name), f"{name} should not remain in chapters_reference"


def test_ch_team_renders_roster() -> None:
    empty = _build_ch_team(None)
    assert "CH_TEAM: LIVE PROJECT ROSTER" in empty
    assert "no peer agents on this project yet" in empty

    populated = _build_ch_team(
        [{"agent_display_name": "tester", "agent_id": "uuid-1", "agent_name": "qa", "execution_status": "working"}]
    )
    assert "uuid-1" in populated
    assert "working" in populated


def test_ch_messaging_states_authority_rule() -> None:
    rendered = _build_ch_messaging()
    assert "CH_MESSAGING: WHO AUTHORS WORK" in rendered
    assert "ORCHESTRATOR authors WORK" in rendered


def test_ch_messaging_includes_board_reply_protocol() -> None:
    rendered = _build_ch_messaging()
    assert "MESSAGE BOARD" in rendered
    assert "get_my_turn" in rendered
    assert "set_next_actor" in rendered
    assert "append-only" in rendered.lower()


def test_thread_loop_directive_states_loop_and_termination() -> None:
    from giljo_mcp.services.protocol_sections.chapters_coordination import _build_thread_loop_directive

    rendered = _build_thread_loop_directive()
    assert "LOOP / SLEEP DIRECTIVE" in rendered
    assert "TERMINATION" in rendered
    assert "resolved" in rendered
    assert "closed" in rendered
    assert "get_my_turn" in rendered
    assert "set_agent_status" in rendered
    assert "sleep 1" in rendered


def test_ch_orchestrator_authority_branches_on_mode() -> None:
    cli = _build_ch_orchestrator_authority(cli_mode=True)
    multi = _build_ch_orchestrator_authority(cli_mode=False)
    assert "CLI SUBAGENT MODE" in cli
    assert "MULTI-TERMINAL MODE" in multi
    assert "CH_AUTHORITY: YOU AUTHOR WORK" in cli
