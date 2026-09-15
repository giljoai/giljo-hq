# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio

import pytest

from giljo_mcp.domain import VALID_UPDATE_STATUSES


def _served_status_enum() -> set[str]:
    from api.endpoints.mcp_tools import mcp

    async def _read() -> set[str]:
        tools = await mcp.list_tools()
        tool = next(t for t in tools if t.name == "update_project")
        prop = (tool.input_schema or {}).get("properties", {}).get("status", {})
        enum = prop.get("enum")
        assert enum is not None, (
            "update_project.status must expose an enum on the wire -- a small model that "
            "reads only the schema has no other way to learn the settable values, and this "
            "is the parameter that runs the archive lifecycle."
        )
        return set(enum)

    return asyncio.run(_read())


def test_served_status_enum_matches_the_domains_settable_set() -> None:
    domain = {s.value for s in VALID_UPDATE_STATUSES}
    served = _served_status_enum()

    assert served - {""} == domain, (
        "update_project.status's served enum has drifted from VALID_UPDATE_STATUSES.\n"
        f"  served (minus the keep-current sentinel): {sorted(served - {''})}\n"
        f"  domain VALID_UPDATE_STATUSES:             {sorted(domain)}\n"
        "Update _UpdatableStatus in api/endpoints/mcp_tools/_project_tools.py to match."
    )


def test_keep_current_sentinel_is_offered() -> None:
    assert "" in _served_status_enum(), (
        "The empty-string keep-current sentinel must remain in the enum -- update_project "
        "is a partial-update tool and status is optional."
    )


@pytest.mark.parametrize("terminal_only", ["terminated", "deleted"])
def test_derived_terminal_states_are_not_offered_as_settable(terminal_only: str) -> None:
    assert terminal_only not in _served_status_enum(), (
        f"'{terminal_only}' is not a settable status -- it must not appear in the enum."
    )
