# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.thread_refs import apply_thread_reference


_THREAD = "0b2f6a10-dead-4beef-9999-abcdefabcdef"
_PLACEHOLDER = "thread_id=<your coordination thread>"


def _orchestrator_protocol(comm_thread_id: str | None) -> str:
    return _generate_orchestrator_protocol(
        "JOB-9459",
        "tk_tsk9459",
        "EXEC-9459",
        "multi_terminal",
        comm_thread_id=comm_thread_id,
    )


class TestAppliedToTheRealOrchestratorProtocol:

    def test_every_placeholder_call_site_is_replaced(self):
        protocol = _orchestrator_protocol(_THREAD)
        assert _PLACEHOLDER not in protocol, "no call site may keep the unresolvable placeholder"
        assert f'thread_id="{_THREAD}"' in protocol

    def test_the_phase1_line_names_the_thread(self):
        protocol = _orchestrator_protocol(_THREAD)
        assert f"Your coordination thread is `{_THREAD}`" in protocol

    def test_the_phase1_line_states_a_fact_and_does_not_instruct_a_join(self):
        protocol = _orchestrator_protocol(_THREAD)
        line = next(ln for ln in protocol.splitlines() if "Your coordination thread is" in ln)
        assert "the server enrolled you" in line
        assert "join_thread" not in line

    def test_none_keeps_the_historical_placeholder_render(self):
        protocol = _orchestrator_protocol(None)
        assert _PLACEHOLDER in protocol
        assert "Your coordination thread is" not in protocol


class TestDegradation:

    def test_drifted_body_is_returned_unchanged(self, caplog):
        drifted = "a protocol whose anchors were renamed by some later edit"
        assert apply_thread_reference(drifted, _THREAD) == drifted
        assert any("placeholder not found" in r.message for r in caplog.records)

    def test_empty_protocol_is_returned_unchanged(self):
        assert apply_thread_reference("", _THREAD) == ""

    def test_no_thread_id_is_returned_unchanged(self):
        body = f"drain with get_thread_history({_PLACEHOLDER}, ...)"
        assert apply_thread_reference(body, None) == body
