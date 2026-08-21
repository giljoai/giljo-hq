# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9464 -- the summary description teaches length, the wrong variable.

TSK-9450 (merged 0e66e7030) fixed the REACTIVE half: the rejection message a
caller sees AFTER an absorbed call is refused now teaches reordering, not
shortening (see test_tsk9450_absorption_remedy_wording_mcp_boundary.py). It
did not touch what the schema teaches a caller BEFORE they ever call the
tool: both ``write_project_closeout.summary`` and ``write_memory_entry.summary``
describe only a length cap ("Max 1500 chars (server-enforced)"), which
TSK-9450 already measured and proved is not the variable that matters --
absorption swallows whatever FOLLOWS a long free-text field, so length is
irrelevant and argument ORDER is everything.

This test pins the PREVENTIVE half: both descriptions must tell a caller to
send ``summary`` LAST, so the schema cannot silently regress back to teaching
only length. It asserts on MEANING (send last / order / absorption), not
exact prose -- same convention as the TSK-9450 suite.

RED before the fix: neither description mentions ordering at all -- both say
only "Max 1500 chars (server-enforced)." after their one-line synopsis.

This is a schema-level pin, not a behavior change, so it inspects the
registered tool surface directly (same technique as
test_be6042d_mcp_tool_registry_surface.py) rather than driving a live call --
there is no detector or rejection message involved here, only the advertised
description text every connected client sees before it ever calls the tool.
"""

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
    """DoD 2: the 1500-char cap is untouched by adding the ordering clause."""
    description = _summary_description(tool_name).lower()
    assert "1500" in description, (
        f"{tool_name}.summary must still advertise the real 1500-char cap -- this lane adds an "
        f"ordering clause, it does not remove the cap: {description!r}"
    )


@pytest.mark.parametrize("tool_name", ["write_project_closeout", "write_memory_entry"])
def test_summary_description_teaches_ordering_not_only_length(tool_name):
    """DoD 1 + 3: the description must teach argument ORDER, the variable that
    actually prevents absorption -- not only length, the variable TSK-9450
    proved does not matter.

    RED before the fix: both descriptions read only "Brief 2-3 sentence
    headline of ... . Max 1500 chars (server-enforced)." -- no mention of
    ordering, last, or absorption at all.
    """
    description = _summary_description(tool_name).lower()
    assert "last" in description, (
        f"{tool_name}.summary must tell the caller to send it LAST -- the one thing that actually "
        f"prevents absorption -- but it only teaches length: {description!r}"
    )
    assert any(word in description for word in ("absorb", "order")), (
        f"{tool_name}.summary must frame the 'last' instruction as an ordering/absorption remedy, "
        f"not an unexplained instruction: {description!r}"
    )
