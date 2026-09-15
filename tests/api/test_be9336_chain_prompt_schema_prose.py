# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from api.endpoints.prompts import _build_conductor_bootstrap
from api.schemas.prompt import ChainPromptResponse


_CHAPTER_BODY_MARKERS = (
    "AGENT TEMPLATES",
    "ORDER OF OPERATIONS",
    "STAND UP THE HUB THREAD",
    "AUTO-CONTINUE LOOP",
)


def _bootstrap(phase: str) -> str:
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
    parts = [ChainPromptResponse.__doc__ or ""]
    parts.extend(f.description or "" for f in ChainPromptResponse.model_fields.values())
    return "\n".join(parts).lower()


def test_bootstrap_is_thin_and_project_less() -> None:
    for phase, fetch_call in (("staging", "get_staging_instructions("), ("implementation", "get_job_mission(")):
        prompt = _bootstrap(phase)

        assert fetch_call in prompt, f"{phase} bootstrap must tell the conductor to fetch its own protocol"
        for marker in _CHAPTER_BODY_MARKERS:
            assert marker not in prompt, f"{phase} bootstrap must not inline the chapter body {marker!r}"

        assert "project-less" in prompt.lower(), f"{phase} bootstrap must identify a project-less conductor"


def test_schema_prose_does_not_claim_the_full_protocol() -> None:
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
    description = (ChainPromptResponse.model_fields["orchestrator_job_id"].description or "").lower()

    assert "for the head project" not in description, (
        "orchestrator_job_id is the run's dedicated project-less conductor job, NOT the head "
        "project's orchestrator (see test_bootstrap_is_thin_and_project_less)"
    )
    assert "conductor" in description, "orchestrator_job_id's description must name the conductor"
    assert "project-less" in description, "orchestrator_job_id's description must say the conductor owns no project"


def test_schema_prose_uses_canonical_chain_vocabulary() -> None:
    prose = _schema_prose()

    assert "sequential multi-project run" not in prose, "use the canonical term: chain"
    assert "sequencerun uuid" not in prose, "run_id is the chain run's UUID; do not expose the internal model name"
