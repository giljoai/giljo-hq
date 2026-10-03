# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from pathlib import Path

from api.endpoints import ai_tools, connect_page


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((REPO_ROOT / "tests" / "fixtures" / "mcp_setup_command_parity.json").read_text("utf-8"))
SERVER_URL = FIXTURE["inputs"]["server_url"]
API_KEY = FIXTURE["inputs"]["api_key"]
COMMANDS = FIXTURE["commands"]


def test_fixture_has_every_harness_the_page_documents():
    for key in ("claude_code_oauth", "codex_oauth", "opencode_oauth", "opencode", "generic_mcp"):
        assert key in COMMANDS, f"fixture missing {key}: connect.md and the wizard would drift unseen"


def test_backend_generators_for_connect_md_equal_fixture():
    assert ai_tools.get_opencode_oauth_config(SERVER_URL) == COMMANDS["opencode_oauth"]
    assert ai_tools.get_opencode_config(SERVER_URL, API_KEY) == COMMANDS["opencode"]
    assert ai_tools.get_generic_mcp_config(SERVER_URL, API_KEY) == COMMANDS["generic_mcp"]


def test_rendered_oauth_page_embeds_the_fixture_commands_verbatim():
    page = connect_page.render_connect_md(SERVER_URL)
    for key in ("claude_code_oauth", "codex_oauth", "opencode_oauth"):
        assert COMMANDS[key] in page, f"connect.md OAuth section drifted from fixture entry {key}"


def test_rendered_key_page_embeds_the_fixture_commands_with_placeholder_key():
    page = connect_page.render_connect_md("http://lan.test:7272", api_key=API_KEY)
    lan = lambda cmd: cmd.replace(SERVER_URL, "http://lan.test:7272")  # noqa: E731
    for key in ("claude_code", "codex_cli", "opencode", "generic_mcp"):
        assert lan(COMMANDS[key]).strip() in page, f"connect.md key section drifted from fixture entry {key}"
