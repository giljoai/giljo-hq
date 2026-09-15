# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    params = set(inspect.signature(compose_template_identity).parameters)
    assert params == {"identity_template", "execution"}, (
        f"compose_template_identity gained a parameter: {params}. If a depth argument was "
        "added, BE-9322 Finding 5 changed and depth_agent_templates now affects spawned "
        "agent identity -- update the field description in api/endpoints/users.py."
    )


def test_full_persona_is_always_emitted_regardless_of_depth_setting():
    identity = compose_template_identity(_template(), _execution())

    assert _USER_INSTRUCTIONS in identity, "role prose missing from composed identity"
    for rule in _RULES:
        assert rule in identity, f"behavioral rule missing from composed identity: {rule!r}"
    for criterion in _CRITERIA:
        assert criterion in identity, f"success criterion missing from composed identity: {criterion!r}"
    assert "IMPLEMENTER" in identity, "role label missing from the framing directive"


def test_system_instructions_stay_out_of_identity():
    identity = compose_template_identity(_template(), _execution())
    assert "MCP bootstrap prose" not in identity


def test_identity_is_byte_identical_across_repeated_composition():
    first = compose_template_identity(_template(), _execution())
    second = compose_template_identity(_template(), _execution())
    assert first == second
