# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9336: ChainPromptResponse's published prose must describe what the chain
prompt endpoints actually return.

Post-BE-6191 both chain prompt endpoints return a THIN bootstrap for the run's
DEDICATED, PROJECT-LESS conductor. The schema kept the pre-BE-6191 wording — "the
full orchestrator protocol (with chain chapters)" for "the head project" — and
nothing compared the two, so the contract surface stayed wrong. The QA harness
built Suite E's E4/E5 assertions on that description and specified a text-equality
comparison between the bootstrap and the full protocol; those assertions would have
gone permanently red against CORRECT behaviour.

Failing layer: the OpenAPI contract surface (``api/schemas/prompt.py``). This test
runs at that layer, but it does not merely assert that the prose says what the prose
says — it first MEASURES the behaviour by calling the pure bootstrap builder the
endpoints use, then asserts the published prose is consistent with that measurement.

Parallel-safe: no DB, no fixtures, no module-level mutable state. Edition Scope: CE.
"""

from __future__ import annotations

from api.endpoints.prompts import _build_conductor_bootstrap
from api.schemas.prompt import ChainPromptResponse


# Chapter-body markers. The bootstrap may NAME the chapters it tells the conductor
# to fetch; inlining their BODY is the fat-paste BE-6191 removed. Same literals the
# BE-6191 endpoint tests pin.
_CHAPTER_BODY_MARKERS = (
    "AGENT TEMPLATES",
    "ORDER OF OPERATIONS",
    "STAND UP THE HUB THREAD",
    "AUTO-CONTINUE LOOP",
)


def _bootstrap(phase: str) -> str:
    """Render the real prompt body an endpoint returns, without touching the DB."""
    return _build_conductor_bootstrap(
        identity={
            "agent_id": "agent-be9336",
            "job_id": "job-be9336",
            "run_id": "run-be9336",
            "project_id": None,
        },
        mcp_url="http://127.0.0.1:8000/mcp",
        phase=phase,
        harness_is_claude=False,
    )


def _schema_prose() -> str:
    """Everything ChainPromptResponse publishes into the OpenAPI document."""
    parts = [ChainPromptResponse.__doc__ or ""]
    parts.extend(f.description or "" for f in ChainPromptResponse.model_fields.values())
    return "\n".join(parts).lower()


def test_bootstrap_is_thin_and_project_less() -> None:
    """MEASUREMENT: establish what the endpoints actually return.

    This is the ground truth the prose assertions below are checked against. If this
    ever goes red the endpoint behaviour changed, and the prose test's premise — not
    its wording — is what needs revisiting.
    """
    for phase, fetch_call in (("staging", "get_staging_instructions("), ("implementation", "get_job_mission(")):
        prompt = _bootstrap(phase)

        # THIN: it instructs the conductor to fetch its protocol rather than carrying it.
        assert fetch_call in prompt, f"{phase} bootstrap must tell the conductor to fetch its own protocol"
        for marker in _CHAPTER_BODY_MARKERS:
            assert marker not in prompt, f"{phase} bootstrap must not inline the chapter body {marker!r}"

        # PROJECT-LESS CONDUCTOR: not the head project's orchestrator.
        assert "project-less" in prompt.lower(), f"{phase} bootstrap must identify a project-less conductor"


def test_schema_prose_does_not_claim_the_full_protocol() -> None:
    """The published prose must not sell the thin bootstrap as the full protocol."""
    prose = _schema_prose()

    assert "full orchestrator protocol" not in prose, (
        "ChainPromptResponse must not describe its response as the full orchestrator "
        "protocol — BE-6191 made it a thin bootstrap (see test_bootstrap_is_thin_and_project_less)"
    )
    assert "full conductor protocol prompt" not in prose, (
        "the prompt field must not be described as the full conductor protocol — it is a bootstrap"
    )
    assert "bootstrap" in prose, "the prose must name what the response actually is: a bootstrap"


def test_orchestrator_job_id_prose_names_the_conductor_not_the_head_project() -> None:
    """orchestrator_job_id carries the project-less conductor's job, not the head project's."""
    description = (ChainPromptResponse.model_fields["orchestrator_job_id"].description or "").lower()

    # The false ATTRIBUTION, not the words — the corrected prose may (and does) still
    # mention the head project in order to rule it out.
    assert "for the head project" not in description, (
        "orchestrator_job_id is the run's dedicated project-less conductor job, NOT the head "
        "project's orchestrator (see test_bootstrap_is_thin_and_project_less)"
    )
    assert "conductor" in description, "orchestrator_job_id's description must name the conductor"
    assert "project-less" in description, "orchestrator_job_id's description must say the conductor owns no project"


def test_schema_prose_uses_canonical_chain_vocabulary() -> None:
    """Customer-visible contract prose uses chain/conductor, not 'sequence'/'sequential'."""
    prose = _schema_prose()

    assert "sequential multi-project run" not in prose, "use the canonical term: chain"
    assert "sequencerun uuid" not in prose, "run_id is the chain run's UUID; do not expose the internal model name"
