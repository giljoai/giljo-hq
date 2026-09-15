# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio




def test_health_check_version_is_installed_version() -> None:
    from giljo_mcp.services.orchestration_service import OrchestrationService
    from giljo_mcp.services.version_service import get_installed_version

    result = asyncio.run(OrchestrationService.health_check())

    assert result["version"] == get_installed_version(), (
        "health_check version must equal the installed VERSION, not a hardcoded literal"
    )
    assert result["version"] != "1.0.0" or get_installed_version() == "1.0.0", (
        "the stale hardcoded '1.0.0' must be gone (unless the installed version genuinely is 1.0.0)"
    )




def _drive(execution_mode: str = "multi_terminal"):
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    return _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2"],
        current_index=0,
        execution_mode=execution_mode,
        conductor_agent_id="cond-1",
        job_id="job-real-99",
    )


def test_chain_drive_uses_ready_to_advance_signal() -> None:
    chapter = _drive()
    low = chapter.lower()

    assert "ready_to_advance" in chapter, "CH_CHAIN_DRIVE must reference ready_to_advance as the advance signal"
    assert "do not advance on status" in low, "the 'do NOT advance on status alone' guard must be kept"


def test_chain_drive_signal_prose_mode_agnostic_byte_identical() -> None:

    def _signal_region(text: str) -> str:
        start = text.find("STEP B — WAIT FOR")
        assert start != -1, "CH_CHAIN_DRIVE must contain STEP B"
        return text[start:]

    assert _signal_region(_drive("multi_terminal")) == _signal_region(_drive("claude_code_cli")), (
        "the advance-signal prose (STEP B + crash-resume) must be byte-identical across execution modes"
    )
