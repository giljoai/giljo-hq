# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from pathlib import Path

from api.endpoints import ai_tools
from giljo_mcp import branding


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "mcp_setup_command_parity.json"


def test_frontend_branding_declares_same_mcp_alias():
    js_branding = (REPO_ROOT / "frontend" / "src" / "branding.js").read_text(encoding="utf-8")
    expected_line = f"export const MCP_ALIAS = '{branding.MCP_ALIAS}'"
    assert expected_line in js_branding, (
        f"frontend/src/branding.js MCP_ALIAS export does not match backend "
        f"branding.MCP_ALIAS={branding.MCP_ALIAS!r}; expected line {expected_line!r}"
    )


def test_ai_tools_py_has_no_stale_hardcoded_alias():
    source = (REPO_ROOT / "api" / "endpoints" / "ai_tools.py").read_text(encoding="utf-8")
    assert '"giljo_mcp"' not in source
    assert "'giljo_mcp'" not in source


def test_use_mcp_config_js_has_no_stale_hardcoded_alias():
    source = (REPO_ROOT / "frontend" / "src" / "composables" / "useMcpConfig.js").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "//")):
            continue
        assert "giljo_mcp" not in line, f"stale hardcoded alias in useMcpConfig.js: {line!r}"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_inputs_are_present_and_well_formed():
    fixture = _load_fixture()
    inputs = fixture["inputs"]
    assert inputs["server_url"] == "https://app.giljo.ai"
    assert inputs["api_key"] == "tk_test_api_key_0000000000000000"


def test_backend_generators_byte_equal_shared_fixture():
    fixture = _load_fixture()
    server_url = fixture["inputs"]["server_url"]
    api_key = fixture["inputs"]["api_key"]

    generated = {
        "claude_code": ai_tools.get_claude_code_config(server_url, api_key),
        "codex_cli": ai_tools.get_codex_config(server_url, api_key),
        "claude_desktop": ai_tools.get_claude_desktop_config(server_url, api_key),
        "claude_code_oauth": ai_tools.get_claude_code_oauth_config(server_url),
        "codex_oauth": ai_tools.get_codex_oauth_config(server_url),
        "claude_desktop_oauth": ai_tools.get_claude_desktop_oauth_config(),
        "opencode_oauth": ai_tools.get_opencode_oauth_config(server_url),
        "opencode": ai_tools.get_opencode_config(server_url, api_key),
        "generic_mcp": ai_tools.get_generic_mcp_config(server_url, api_key),
    }

    expected = fixture["commands"]
    assert generated.keys() == expected.keys(), (
        "generator set in this test no longer matches the fixture's command keys -- "
        "update both the fixture and the frontend vitest mirror if a generator was added/removed"
    )
    for key, expected_value in expected.items():
        assert generated[key] == expected_value, (
            f"backend generator for {key!r} drifted from the shared fixture "
            f"{FIXTURE_PATH}: expected {expected_value!r}, got {generated[key]!r}"
        )


def test_all_commands_carry_the_branding_mcp_alias():
    fixture = _load_fixture()
    for key, value in fixture["commands"].items():
        if key == "claude_desktop_oauth":
            continue
        assert branding.MCP_ALIAS in value, f"{key!r} fixture entry does not contain branding.MCP_ALIAS: {value!r}"
