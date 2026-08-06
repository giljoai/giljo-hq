# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9292b: CH5's final-acceptance prose was extracted to its own module — pin the seam.

``_CLOSING_JOBS_REFERENCE`` (CLOSING JOBS + ACCEPTING A STALLED AGENT) moved out of
``chapters_reference._build_ch5_reference`` for the 800-line file-size guardrail and
that builder's shrink-only length budget.

The hazard an extraction like this creates is specific: someone re-inlines the prose in
CH5 and the extracted module keeps sitting there looking authoritative while rendering
nothing — so every later edit to it is silently dead. Containment alone cannot catch
that (a re-inlined duplicate contains the same text). These tests close it two ways:

  * IDENTITY — the name CH5 interpolates and the module's constant are the SAME object,
    so editing ``closing_jobs.py`` is editing what CH5 renders.
  * SUBSTITUTION — swap that name for a sentinel and the sentinel must appear in the
    render while the real prose disappears. Only a builder that actually interpolates
    the constant can pass; a re-inlined copy fails.

Plus the deliverable itself (the stalled-agent recovery, with its ``report_progress``
prerequisite) reaching the real orchestrator protocol, and the brace hazard the
f-string -> plain-string conversion introduced.

Pure tests (no DB, no module-level mutable state) — parallel-safe under xdist.
Edition Scope: CE.
"""

from __future__ import annotations

import pytest

from giljo_mcp.services.protocol_sections import chapters_reference, closing_jobs
from giljo_mcp.services.protocol_sections.chapters_reference import _build_ch5_reference


def _render() -> str:
    return _build_ch5_reference("p-9292b", "orch-9292b", "multi_terminal", False)


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


def test_ch5_interpolates_the_module_constant_by_identity() -> None:
    """CH5's name and the module's constant are one object — editing the module edits CH5."""
    assert chapters_reference._CLOSING_JOBS_REFERENCE is closing_jobs._CLOSING_JOBS_REFERENCE


def test_ch5_render_is_composed_from_the_constant_not_a_reinlined_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Substituting the constant must change the render — proves the extracted copy is live."""
    real = closing_jobs._CLOSING_JOBS_REFERENCE
    sentinel = "«BE-9292b closing-jobs sentinel»"
    monkeypatch.setattr(chapters_reference, "_CLOSING_JOBS_REFERENCE", sentinel)

    rendered = _render()

    assert sentinel in rendered, "CH5 no longer interpolates _CLOSING_JOBS_REFERENCE — the extracted module is dead"
    assert real not in rendered, "CH5 still carries an inlined copy of the prose alongside the constant"


def test_constant_appears_exactly_once_in_ch5() -> None:
    """One authoritative copy — a second would drift from the first."""
    assert _render().count(closing_jobs._CLOSING_JOBS_REFERENCE) == 1


# ---------------------------------------------------------------------------
# The content the extraction must not lose
# ---------------------------------------------------------------------------


def test_stalled_agent_recovery_survives_into_the_orchestrator_protocol() -> None:
    """The deliverable reaches the real render, not just the builder in isolation."""
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
    # The prerequisite is the whole reason this ships: complete_job on a stalled worker
    # with stranded TODOs returns COMPLETION_BLOCKED without it.
    assert "report_progress(job_id=<stalled job>, todo_items=[...], replace=true)" in ch5
    assert "COMPLETION_BLOCKED" in ch5
    # And the dead end it replaces stays named.
    assert "write_project_closeout(force=true)" in ch5


def test_braces_render_literally_after_the_fstring_conversion() -> None:
    """The constant is a plain string now — doubled braces would leak into agent-facing prose."""
    rendered = _render()

    assert 'result={"summary": ..., "commits": [...]}' in rendered
    assert "{{" not in rendered and "}}" not in rendered
