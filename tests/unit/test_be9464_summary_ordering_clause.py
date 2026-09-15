# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.endpoints.mcp_sdk_server import mcp


def _tool_by_name(name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name!r} is not registered on the live mcp instance")


def _summary_description(tool_name: str) -> str:
    tool = _tool_by_name(tool_name)
    properties = tool.parameters.get("properties", {}) if isinstance(tool.parameters, dict) else {}
    summary_schema = properties.get("summary")
    assert summary_schema is not None, f"{tool_name} has no 'summary' parameter in its schema"
    description = summary_schema.get("description", "")
    assert description, f"{tool_name}.summary has no description at all"
    return description


@pytest.mark.parametrize("tool_name", ["write_project_closeout", "write_memory_entry"])
def test_summary_description_still_advertises_the_real_cap(tool_name):
    description = _summary_description(tool_name).lower()
    assert "1500" in description, (
        f"{tool_name}.summary must still advertise the real 1500-char cap -- this lane adds an "
        f"ordering clause, it does not remove the cap: {description!r}"
    )


@pytest.mark.parametrize("tool_name", ["write_project_closeout", "write_memory_entry"])
def test_summary_description_teaches_ordering_not_only_length(tool_name):
    description = _summary_description(tool_name).lower()
    assert "last" in description, (
        f"{tool_name}.summary must tell the caller to send it LAST -- the one thing that actually "
        f"prevents absorption -- but it only teaches length: {description!r}"
    )
    assert any(word in description for word in ("absorb", "order")), (
        f"{tool_name}.summary must frame the 'last' instruction as an ordering/absorption remedy, "
        f"not an unexplained instruction: {description!r}"
    )
