# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9322 Finding 5 — ``depth_agent_templates`` is misnamed: it does NOT
control what a spawned agent receives as its identity.

Measured behaviour (this project's evidence table): flipping the setting
changes the ``get_context(categories=['agent_templates'])`` ROSTER payload
from 318 to 10,023 characters. What it never touches is the identity handed
to a spawned agent — ``MissionService._resolve_mission_template`` composes
that from the job's ``template_id`` via ``compose_template_identity``, which
is a pure function of ``(template, execution)``. There is no depth parameter
anywhere on that path, and a repo-wide ``grep -n "depth"`` over
``mission_service.py`` / ``mission_assembly.py`` / ``job_lifecycle_service.py``
/ ``agent_job_manager.py`` returns nothing.

This pins the invariant rather than the wording: the FULL persona
(user_instructions + behavioral_rules + success_criteria) is emitted whenever
a template resolves, regardless of any depth setting. If someone later wires
depth into identity composition — making 'basic' silently ship an agent a
trimmed persona — this goes red, which is precisely the regression worth
catching. It is the backend mirror of the black-box plan's B5.

Parallel-safe: pure function under test, no DB, no module-level state.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from giljo_mcp.services.mission_assembly import compose_template_identity


_USER_INSTRUCTIONS = "You implement backend changes with tests first."
_RULES = ["Never bypass the service layer", "Always scope queries by tenant_key"]
_CRITERIA = ["All tests green", "No new lint warnings"]


def _template() -> SimpleNamespace:
    return SimpleNamespace(
        role="implementer",
        user_instructions=_USER_INSTRUCTIONS,
        behavioral_rules=list(_RULES),
        success_criteria=list(_CRITERIA),
        system_instructions="MCP bootstrap prose that must NOT leak into identity",
    )


def _execution() -> SimpleNamespace:
    return SimpleNamespace(agent_name="implementer", agent_display_name="Implementer")


def test_identity_composition_takes_no_depth_parameter():
    """The structural guarantee: depth cannot influence identity because it is
    not an input to the function that builds it."""
    params = set(inspect.signature(compose_template_identity).parameters)
    assert params == {"identity_template", "execution"}, (
        f"compose_template_identity gained a parameter: {params}. If a depth argument was "
        "added, BE-9322 Finding 5 changed and depth_agent_templates now affects spawned "
        "agent identity -- update the field description in api/endpoints/users.py."
    )


def test_full_persona_is_always_emitted_regardless_of_depth_setting():
    """'basic' is the DEFAULT depth_agent_templates value. A spawned agent must
    still get the complete persona -- the setting only trims the get_context roster."""
    identity = compose_template_identity(_template(), _execution())

    assert _USER_INSTRUCTIONS in identity, "role prose missing from composed identity"
    for rule in _RULES:
        assert rule in identity, f"behavioral rule missing from composed identity: {rule!r}"
    for criterion in _CRITERIA:
        assert criterion in identity, f"success criterion missing from composed identity: {criterion!r}"
    assert "IMPLEMENTER" in identity, "role label missing from the framing directive"


def test_system_instructions_stay_out_of_identity():
    """Guard the deliberate exclusion the composer documents: the thin prompt
    already handles MCP bootstrap, so system_instructions must not be duplicated
    into the agent's operating identity."""
    identity = compose_template_identity(_template(), _execution())
    assert "MCP bootstrap prose" not in identity


def test_identity_is_byte_identical_across_repeated_composition():
    """Mirrors the black-box plan's B5 assertion: nothing ambient (a depth
    setting, a user row, a global) may make two compositions of the same
    template differ."""
    first = compose_template_identity(_template(), _execution())
    second = compose_template_identity(_template(), _execution())
    assert first == second
