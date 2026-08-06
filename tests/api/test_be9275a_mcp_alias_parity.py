# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9275a — backend/frontend MCP-alias parity guard.

The setup-wizard connect generators exist in two places that must agree on
the literal MCP server alias: the backend reference implementation
(api/endpoints/ai_tools.py, source of truth for the byte-parity contract) and
the frontend byte-mirror (frontend/src/composables/useMcpConfig.js). Both
import their alias from a `branding` module (src/giljo_mcp/branding.py and
frontend/src/branding.js respectively) rather than hardcoding the string, so
this test locks that both branding modules declare the SAME alias and that
neither generator file still hardcodes the pre-rebrand "giljo_mcp" literal.

There is no existing JS-execution harness in this repo's pytest suite (no
Node subprocess runner for frontend unit tests), so cross-language parity is
enforced via a SHARED committed fixture (tests/fixtures/mcp_setup_command_parity.json)
rather than a live cross-language execution: this test calls the REAL backend
generators in api/endpoints/ai_tools.py for a fixed set of inputs and asserts
the output is byte-identical to the fixture; the mirrored
frontend/src/composables/__tests__/useMcpConfig.spec.js asserts the JS
generators' output against the SAME fixture file. If either side's generator
output drifts from the fixture, only that side's test goes red -- the fixture
itself is the shared contract, not derived at test time from either side.
"""

import json
from pathlib import Path

from api.endpoints import ai_tools
from giljo_mcp import branding


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "mcp_setup_command_parity.json"


def test_frontend_branding_declares_same_mcp_alias():
    """frontend/src/branding.js MCP_ALIAS literal must equal the backend's."""
    js_branding = (REPO_ROOT / "frontend" / "src" / "branding.js").read_text(encoding="utf-8")
    expected_line = f"export const MCP_ALIAS = '{branding.MCP_ALIAS}'"
    assert expected_line in js_branding, (
        f"frontend/src/branding.js MCP_ALIAS export does not match backend "
        f"branding.MCP_ALIAS={branding.MCP_ALIAS!r}; expected line {expected_line!r}"
    )


def test_ai_tools_py_has_no_stale_hardcoded_alias():
    """The backend generator reference must not hardcode the pre-rebrand alias."""
    source = (REPO_ROOT / "api" / "endpoints" / "ai_tools.py").read_text(encoding="utf-8")
    assert '"giljo_mcp"' not in source
    assert "'giljo_mcp'" not in source


def test_use_mcp_config_js_has_no_stale_hardcoded_alias():
    """The frontend byte-mirror generator must not hardcode the pre-rebrand alias."""
    source = (REPO_ROOT / "frontend" / "src" / "composables" / "useMcpConfig.js").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "//")):
            continue  # comments/prose may still reference the old alias in history notes
        assert "giljo_mcp" not in line, f"stale hardcoded alias in useMcpConfig.js: {line!r}"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_inputs_are_present_and_well_formed():
    """The shared fixture must declare the exact inputs both generators were called with."""
    fixture = _load_fixture()
    inputs = fixture["inputs"]
    assert inputs["server_url"] == "https://app.giljo.ai"
    assert inputs["api_key"] == "tk_test_api_key_0000000000000000"
    assert inputs["self_signed_https"] is False


def test_backend_generators_byte_equal_shared_fixture():
    """The REAL backend generator output must byte-equal the committed fixture.

    This calls the live functions in api/endpoints/ai_tools.py -- it does not
    hardcode an expected string -- so any drift in the generator's emitted
    command/JSON turns this test red. The frontend implementer's vitest suite
    asserts the SAME fixture against useMcpConfig.js; only one side goes red
    on a genuine emitted-output change.
    """
    fixture = _load_fixture()
    server_url = fixture["inputs"]["server_url"]
    api_key = fixture["inputs"]["api_key"]
    self_signed_https = fixture["inputs"]["self_signed_https"]

    generated = {
        "claude_code": ai_tools.get_claude_code_config(server_url, api_key),
        "codex_cli": ai_tools.get_codex_config(server_url, api_key),
        "claude_desktop": ai_tools.get_claude_desktop_config(server_url, api_key, self_signed_https),
        "gemini_cli": ai_tools.get_gemini_config(server_url, api_key),
        "antigravity_cli": ai_tools.get_antigravity_config(server_url, api_key),
        "claude_code_oauth": ai_tools.get_claude_code_oauth_config(server_url),
        "codex_oauth": ai_tools.get_codex_oauth_config(server_url),
        "gemini_oauth": ai_tools.get_gemini_oauth_config(server_url),
        "claude_desktop_oauth": ai_tools.get_claude_desktop_oauth_config(),
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
    """Every fixture-mirrored command must reference the current MCP_ALIAS, not a stale one.

    claude_desktop_oauth is exempt by design: it has no CLI `mcp add` command
    (the connector is added by name in app/browser settings, not by alias) --
    see get_claude_desktop_oauth_config()'s docstring in api/endpoints/ai_tools.py.
    """
    fixture = _load_fixture()
    for key, value in fixture["commands"].items():
        if key == "claude_desktop_oauth":
            continue
        assert branding.MCP_ALIAS in value, f"{key!r} fixture entry does not contain branding.MCP_ALIAS: {value!r}"
