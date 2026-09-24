# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.handover_template import DEFAULT_HANDOVER_TEMPLATE
from giljo_mcp.services.handover_validation import REQUIRED_HANDOVER_HEADINGS
from giljo_mcp.thin_prompt_generator import build_retirement_prompt


def _prompt(handover_template: str | None = None) -> str:
    return build_retirement_prompt(
        project_id="11111111-1111-1111-1111-111111111111",
        agent_id="orchestrator-1",
        job_id="job-1",
        project_name="BE-9643a",
        handover_template=handover_template,
    )


def test_the_tenant_template_appears_verbatim() -> None:
    custom = (
        "## Context\nWhat this session was.\n\n"
        "## Verify before trusting\n- <claim> -- check with: <command>\n\n"
        "## Waiting on the operator\n- <what needs a human>\n\n"
        "## Cannot testify\n- <what you did not verify>\n\n"
        "## References\n- <path or link>\n"
    )

    prompt = _prompt(custom)

    assert custom.strip() in prompt, "the operator's template did not reach the agent verbatim"


def test_an_account_with_no_template_gets_the_default() -> None:
    prompt = _prompt(None)
    assert DEFAULT_HANDOVER_TEMPLATE.strip() in prompt


def test_a_template_missing_a_heading_is_completed_before_it_reaches_the_agent() -> None:
    prompt = _prompt("## Context\nJust this.\n")

    for heading in REQUIRED_HANDOVER_HEADINGS:
        assert heading in prompt, f"{heading} never reached the agent"
    assert "## Context" in prompt


def test_the_prompt_still_explains_the_gate() -> None:
    prompt = _prompt(None)
    assert 'task_type="HND"' in prompt
    assert "REFUSES" in prompt


def test_every_required_heading_carries_a_prompt_of_its_own() -> None:
    for heading in REQUIRED_HANDOVER_HEADINGS:
        index = DEFAULT_HANDOVER_TEMPLATE.index(heading)
        after = DEFAULT_HANDOVER_TEMPLATE[index + len(heading) :].lstrip("\n")
        assert after.strip(), f"{heading} has no hint under it"
