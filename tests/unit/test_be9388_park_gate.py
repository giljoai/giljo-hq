# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.comm_thread_service import CommThreadService


ME = "lane-A"


def _pending(turn: dict) -> bool:
    return CommThreadService._has_pending_work(turn)


def _turn(threads=(), directed=(), loops=(), agent_id: str | None = ME) -> dict:
    return {
        "agent_id": agent_id,
        "count": len(threads),
        "threads": list(threads),
        "directed_action": list(directed),
        "loop_directives": list(loops),
    }


MINE = {"thread_id": "t1", "next_action_owner": ME}
BROADCAST = {"thread_id": "t2", "next_action_owner": "all"}
SOMEONE_ELSE = {"thread_id": "t3", "next_action_owner": "lane-B"}
UNOWNED = {"thread_id": "t4", "next_action_owner": None}


def test_work_that_must_wake_an_agent():
    assert _pending(_turn(threads=[MINE])) is True, "a baton naming me is my turn"
    assert _pending(_turn(directed=[{"thread_id": "t9"}])) is True, "the BE-9207 directed axis is untouched"
    assert _pending(_turn(threads=[BROADCAST], directed=[{"thread_id": "t2"}])) is True


def test_state_that_must_not_pre_empt_the_park():
    assert _pending(_turn()) is False
    assert _pending(_turn(threads=[BROADCAST])) is False, "a standing 'all' baton is a state, not an event"
    assert _pending(_turn(loops=[{"thread_id": "t5"}])) is False, "loop directives stay excluded (BE-9296a)"


def test_another_lanes_baton_is_not_my_turn():
    assert _pending(_turn(threads=[SOMEONE_ELSE])) is False
    assert _pending(_turn(threads=[UNOWNED])) is False, "an unowned thread holds nobody's turn"


def test_a_missing_agent_id_can_never_match_an_unowned_thread():
    assert _pending(_turn(threads=[UNOWNED], agent_id=None)) is False


def test_a_payload_without_the_optional_keys_is_not_pending():
    assert _pending({"agent_id": ME}) is False
    assert _pending({"agent_id": ME, "threads": None, "directed_action": None}) is False
