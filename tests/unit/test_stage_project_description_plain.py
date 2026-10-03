# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re

from api.endpoints.mcp_sdk_server import mcp


def _tool():
    return next(t for t in mcp._tool_manager.list_tools() if t.name == "stage_project")


def test_description_states_gate_scope_and_restage_effect():
    d = _tool().description
    assert "human approval gate" in d
    assert "private Giljo HQ workspace" in d
    assert "No outside service is contacted" in d
    assert "launch_implementation" in d
    assert "restage" in d
    assert "clears the mission" in d
    assert "retires the earlier orchestrator" in d


def test_description_has_no_all_caps_directives():
    d = _tool().description
    for banned in ("STOP", "HUMAN GATE", "REVERSE GEAR"):
        assert banned not in d
    assert not re.findall(r"\b[A-Z]{4,}\b", d.replace("EXECUTION_MODE_REQUIRED", ""))


def test_hints_unchanged():
    a = _tool().annotations
    assert a.destructive_hint is True
    assert a.read_only_hint is False
    assert a.open_world_hint is False
