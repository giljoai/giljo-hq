# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.protocol_sections import chapters_reference, closing_jobs
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch5_reference


def _render() -> str:
    return _build_ch5_reference("p-9292b", "orch-9292b", "multi_terminal", False)




def test_ch5_interpolates_the_module_constant_by_identity() -> None:
    assert chapters_reference._CLOSING_JOBS_REFERENCE is closing_jobs._CLOSING_JOBS_REFERENCE


def test_ch5_render_is_composed_from_the_constant_not_a_reinlined_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = closing_jobs._CLOSING_JOBS_REFERENCE
    sentinel = "«BE-9292b closing-jobs sentinel»"
    monkeypatch.setattr(chapters_reference, "_CLOSING_JOBS_REFERENCE", sentinel)

    rendered = _render()

    assert sentinel in rendered, "CH5 no longer interpolates _CLOSING_JOBS_REFERENCE — the extracted module is dead"
    assert real not in rendered, "CH5 still carries an inlined copy of the prose alongside the constant"


def test_constant_appears_exactly_once_in_ch5() -> None:
    assert _render().count(closing_jobs._CLOSING_JOBS_REFERENCE) == 1




def test_stalled_agent_recovery_survives_into_the_orchestrator_protocol() -> None:
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    chapters = _build_orchestrator_protocol(
        cli_mode=False,
        project_id="p-9292b",
        orchestrator_id="orch-9292b",
        tenant_key="tk-9292b",
        include_implementation_reference=True,
    )
    ch5 = chapters.get("ch5_reference") or ""

    assert "ACCEPTING A STALLED AGENT" in ch5
    assert "report_progress(job_id=<stalled job>, todo_items=[...], replace=true)" in ch5
    assert "COMPLETION_BLOCKED" in ch5
    assert "write_project_closeout(force=true)" in ch5


def test_braces_render_literally_after_the_fstring_conversion() -> None:
    rendered = _render()

    assert 'result={"summary": ..., "commits": [...]}' in rendered
    assert "{{" not in rendered and "}}" not in rendered
