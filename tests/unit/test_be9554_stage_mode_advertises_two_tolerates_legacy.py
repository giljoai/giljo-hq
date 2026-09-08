# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9554 -- ``stage_project.mode`` advertises two choices and still tolerates six.

Before this change the parameter was a ``Literal`` carrying six values, four of which
(``claude``/``codex``/``gemini``/``antigravity``) were legacy harness-name aliases the
description then spent ~700 characters warning the caller off. A model choosing from
that enum picked a discouraged value two times out of three by construction, which is
the "action-enum tools split or simplified wherever a small model would misfire" case.

The fix is deliberately NOT a narrowed ``Literal``. A ``Literal`` validates, so
narrowing it would make the boundary REJECT the legacy names -- and the ruling is
**tolerance, not removal**: callers registered against the old surface keep working,
they are simply no longer offered the dead options. So the parameter is typed ``str``
(accepts anything the service accepts) with an ``enum`` published in the JSON schema
for the two real choices.

That combination is easy to break by "tidying" the type back to a ``Literal``, and the
break would be invisible until an old client 422s. Both halves are pinned here.
"""

import asyncio

import pytest


LEGACY_ALIASES = ("claude", "codex", "gemini", "antigravity")
REAL_CHOICES = ("multi_terminal", "subagent")


def _mode_schema() -> dict:
    """The `mode` property exactly as an MCP client receives it."""
    from api.endpoints.mcp_tools import mcp

    async def _read() -> dict:
        tools = await mcp.list_tools()
        tool = next(t for t in tools if t.name == "stage_project")
        return (tool.input_schema or {}).get("properties", {}).get("mode", {})

    return asyncio.run(_read())


def test_only_the_two_real_choices_are_advertised() -> None:
    enum = _mode_schema().get("enum")
    assert enum is not None, "mode must publish an enum -- it is the one question staging asks."
    assert set(enum) == set(REAL_CHOICES), (
        f"mode should advertise exactly {sorted(REAL_CHOICES)}; got {sorted(enum)}. "
        "The legacy harness-name aliases must not be offered to a caller choosing a value."
    )


@pytest.mark.parametrize("alias", LEGACY_ALIASES)
def test_legacy_aliases_are_not_advertised(alias: str) -> None:
    assert alias not in (_mode_schema().get("enum") or []), (
        f"'{alias}' is a legacy harness-name alias. It stays ACCEPTED at runtime, but "
        "offering it in the schema is what made this parameter mis-pickable."
    )


def test_the_type_still_accepts_a_legacy_value() -> None:
    """The tolerance half. A narrowed ``Literal`` would publish the same enum as the
    test above expects while silently making the boundary reject old callers -- so
    assert on the TYPE, which is what decides whether a legacy value validates."""
    schema = _mode_schema()
    assert schema.get("type") == "string", (
        "mode must stay a plain string so legacy harness-name values still validate at "
        "the boundary (tolerance, not removal). A narrowed Literal would publish the "
        "right enum and break every caller still sending 'claude'/'codex'/'gemini'/"
        f"'antigravity'. Got type={schema.get('type')!r}."
    )


def test_the_description_no_longer_spends_itself_warning_about_dead_values() -> None:
    """The saving only lands if the prose that existed to warn callers off the legacy
    values went with them."""
    from api.endpoints.mcp_tools import mcp

    async def _desc() -> str:
        tools = await mcp.list_tools()
        return next(t for t in tools if t.name == "stage_project").description or ""

    description = asyncio.run(_desc())
    for alias in LEGACY_ALIASES:
        assert f"'{alias}'" not in description, (
            f"stage_project's description still argues about the legacy alias '{alias}'. "
            "Once the value is not offered, the warning is dead weight on every call."
        )
