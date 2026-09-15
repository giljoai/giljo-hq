# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio

import pytest


LEGACY_ALIASES = ("claude", "codex", "gemini", "antigravity")
REAL_CHOICES = ("multi_terminal", "subagent")


def _mode_schema() -> dict:
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
    schema = _mode_schema()
    assert schema.get("type") == "string", (
        "mode must stay a plain string so legacy harness-name values still validate at "
        "the boundary (tolerance, not removal). A narrowed Literal would publish the "
        "right enum and break every caller still sending 'claude'/'codex'/'gemini'/"
        f"'antigravity'. Got type={schema.get('type')!r}."
    )


def test_the_description_no_longer_spends_itself_warning_about_dead_values() -> None:
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
