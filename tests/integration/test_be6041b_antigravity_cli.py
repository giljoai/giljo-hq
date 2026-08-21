# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6041b regression suite: Antigravity CLI (`agy`) platform support.

P1 promise: selecting platform ``antigravity_cli`` NEVER 400/422/500s anywhere
in the backend; agy executions record under ``tool_type='antigravity'``; a
switching user gets a correct agy connect config.

Three regression tests at the failing layers (CLAUDE.md / BE-5042 lesson):

1. MCP @mcp.tool BOUNDARY: ``giljo_setup`` accepts ``platform='antigravity_cli'``
   through the FastMCP transport and returns a config (no 422). A service-layer
   test would NOT catch a Literal-rejection at the wrapper boundary.
2. SERVICE / rendering map: ``antigravity_cli`` execution-mode renders via the
   generic (plaintext) path and the tool_type CHECK accepts ``'antigravity'`` --
   the template_renderer footgun (cli_tool='antigravity' must NOT fall through to
   Claude YAML) and the assembler platform contract.
3. FileStaging zip-structure: combined staging for ``antigravity_cli`` produces a
   single nested ``plugins/giljoai/`` bundle (no ValueError) with plugin.json +
   agents/<name>/agent.json + skills/<name>/SKILL.md (BE-6041c P2 packaging).

Parallel-safe (xdist -n auto): no module-level mutable state, each test owns its
setup, DB-touching tests use the function-scoped ``db_session`` fixture.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Test 1 -- MCP @mcp.tool BOUNDARY (the 422 hides here)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def giljo_setup_client(monkeypatch, db_manager):
    """In-memory FastMCP client wired for giljo_setup boundary tests.

    Mirrors tests/integration/test_imp6038_giljo_setup_ack_mcp_boundary.py:
    stub bootstrap_setup, wire the test db_manager, scope the tenant, neutralise
    post-call side effects.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    class _StubAccessor:
        # BE-9385b: giljo_setup forwards the resolved harness so the install
        # prose can target the repository. **_kwargs rather than a named
        # parameter so this stub stops breaking every time the real
        # accessor gains an argument it does not care about.
        async def bootstrap_setup(self, platform: str, user_id=None, **_kwargs):
            return {"status": "ready", "platform": platform}

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def test_giljo_setup_accepts_antigravity_cli_through_transport(giljo_setup_client):
    """giljo_setup(platform='antigravity_cli') returns a config -- no 422 at the boundary."""
    new_client, _tenant_key = giljo_setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "antigravity_cli"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload.get("platform") == "antigravity_cli"


# ---------------------------------------------------------------------------
# Test 2 -- SERVICE / rendering map (tool_type='antigravity', generic path)
# ---------------------------------------------------------------------------


def test_template_renderer_routes_antigravity_to_generic():
    """cli_tool='antigravity' renders via the generic (plaintext) path, NOT Claude YAML.

    Footgun guard: under D1-B antigravity is NOT in the gemini mapping; if it fell
    through render_template it would silently emit Claude YAML frontmatter.
    """
    from giljo_mcp.template_renderer import render_generic_agent, render_template

    template = AgentTemplate(
        id="tmpl-antigravity",
        tenant_key="tenant-xyz",
        name="implementer",
        role="Implementation specialist",
        version="1.0.0",
        system_instructions="Do the thing.",
        is_active=True,
        cli_tool="antigravity",
    )

    rendered = render_template(template)

    assert rendered == render_generic_agent(template)
    # Claude YAML frontmatter starts with a '---' fence; generic plaintext must not.
    assert not rendered.lstrip().startswith("---")


def test_assembler_accepts_antigravity_cli_and_labels_platform():
    """AgentTemplateAssembler.assemble(..., 'antigravity_cli') emits the nested plugin bundle.

    BE-6041c (P2): antigravity is a NESTED plugin bundle, not a flat .md set. The
    assembler returns a plugin manifest + per-agent nested ``config.customAgent``
    agent.json dicts (spike C2/C3), installed via `agy plugin install`.
    """
    from giljo_mcp.tools.agent_template_assembler import VALID_PLATFORMS, AgentTemplateAssembler

    assert "antigravity_cli" in VALID_PLATFORMS

    templates = [
        AgentTemplate(
            id="tmpl-a",
            tenant_key="tenant-xyz",
            name="implementer",
            role="Implementation specialist",
            version="1.0.0",
            system_instructions="Do the thing.",
            is_active=True,
            cli_tool="antigravity",
        )
    ]

    result = AgentTemplateAssembler().assemble(templates, "antigravity_cli")

    assert result["platform"] == "antigravity_cli"
    assert result["template_count"] == 1
    assert result["plugin_name"] == "giljoai"

    # plugin.json manifest is the minimal validator-accepted shape (spike C2 Q4).
    manifest = result["plugin_manifest"]
    assert set(manifest) == {"name", "version", "description"}

    # Each agent carries a nested config.customAgent agent.json (NOT flat markdown).
    agent = result["agents"][0]
    assert agent["agent_dir"] == "implementer"
    custom = agent["agent_json"]["config"]["customAgent"]
    assert "mcp_servers" in custom["systemPromptConfig"]["includeSections"]
    assert custom["systemPromptSections"][0]["content"]

    # Install path is the spike-confirmed plugin root, registered via `agy plugin install`.
    assert "config/plugins/giljoai" in result["install_paths"]["plugin_root"]
    assert result["install_paths"]["install_command"].startswith("agy plugin install")


def test_execution_mode_gate_accepts_antigravity_cli():
    """antigravity_cli is a TOLERATED legacy execution mode (write-boundary membership).

    BE-9035c collapsed 6 modes -> 2 canonical (multi_terminal | subagent). The legacy
    antigravity_cli token is still ACCEPTED at the write boundary (tolerance set) and
    folds to 'subagent' via normalize_execution_mode, but it is NOT one of the two
    VALID canonical modes. The gate accepting a legacy antigravity project is the intent.
    """
    from giljo_mcp.platform_registry import (
        ACCEPTED_EXECUTION_MODES,
        VALID_EXECUTION_MODES,
        normalize_execution_mode,
    )

    assert "antigravity_cli" in ACCEPTED_EXECUTION_MODES
    assert "antigravity_cli" not in VALID_EXECUTION_MODES
    assert normalize_execution_mode("antigravity_cli") == "subagent"


# ---------------------------------------------------------------------------
# Test 3 -- FileStaging zip-structure (no ValueError, valid bundle)
# ---------------------------------------------------------------------------


async def test_file_staging_antigravity_cli_produces_valid_bundle(db_session: AsyncSession, tmp_path: Path):
    """Combined staging for antigravity_cli yields a single nested plugin bundle, no ValueError.

    BE-6041c (P2): one plugins/giljoai/ tree carrying plugin.json + agents/<name>/agent.json
    + skills/<name>/SKILL.md (spike C3 single-bundle rule).
    """
    import json

    from giljo_mcp.file_staging import FileStaging

    tenant_key = "tenant-antigravity"
    template = AgentTemplate(
        id="tmpl-staging",
        tenant_key=tenant_key,
        name="implementer",
        role="Implementation specialist",
        version="1.0.0",
        system_instructions="Do the thing.",
        is_active=True,
        cli_tool="antigravity",
    )
    db_session.add(template)
    await db_session.commit()

    staging = FileStaging(base_path=tmp_path, db_session=db_session)
    staging_dir = await staging.create_staging_directory(tenant_key, "tok-antigravity")

    zip_path, msg = await staging.stage_combined_setup(staging_dir, tenant_key, db_session, platform="antigravity_cli")

    assert zip_path is not None, msg
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        manifest_raw = zf.read("plugins/giljoai/plugin.json").decode("utf-8")

    # Everything lives under one plugin tree (no bare skills/ or agents/ at root).
    assert "plugins/giljoai/plugin.json" in names, names
    assert any(n.startswith("plugins/giljoai/agents/") and n.endswith("/agent.json") for n in names), names
    assert any(n.startswith("plugins/giljoai/skills/") and n.endswith("SKILL.md") for n in names), names
    assert not any(n.startswith(("skills/", "agents/")) for n in names), names

    # plugin.json is the minimal validator-accepted manifest.
    manifest = json.loads(manifest_raw)
    assert set(manifest) == {"name", "version", "description"}


# ---------------------------------------------------------------------------
# Test 4 -- Focused regression: stage_agent_templates() AGENTS-ONLY ZIP path
#
# BE-6041c gap (flagged by implementer): combined staging is exercised by
# Test 3 above, but stage_agent_templates() is only called transitively.
# This test hits the agents-only ZIP path DIRECTLY to assert the nested
# plugins/giljoai/ tree — with a valid plugin.json and NO bare top-level
# skills/ or agents/ entries (would indicate the nesting guard regressed).
# ---------------------------------------------------------------------------


async def test_stage_agent_templates_antigravity_emits_nested_plugin_bundle(db_session: AsyncSession, tmp_path: Path):
    """stage_agent_templates(platform='antigravity_cli') emits a nested plugin bundle.

    Agents-only ZIP path: plugins/giljoai/plugin.json +
    plugins/giljoai/agents/<name>/agent.json, NO bare skills/ or agents/ at root.
    plugin.json must be valid JSON with exactly {name, version, description}.

    This is the DIRECT regression for the stage_agent_templates() code path
    (not stage_combined_setup); it is NOT exercised by Test 3 above.
    """
    from giljo_mcp.file_staging import FileStaging

    tenant_key = "tenant-agents-only-zip"
    template = AgentTemplate(
        id="tmpl-agents-only",
        tenant_key=tenant_key,
        name="reviewer",
        role="Code review specialist",
        version="1.0.0",
        system_instructions="Review code thoroughly.",
        is_active=True,
        cli_tool="antigravity",
    )
    db_session.add(template)
    await db_session.commit()

    staging = FileStaging(base_path=tmp_path, db_session=db_session)
    staging_dir = await staging.create_staging_directory(tenant_key, "tok-agents-only")

    # Call the AGENTS-ONLY path (not stage_combined_setup).
    zip_path, msg = await staging.stage_agent_templates(staging_dir, tenant_key, db_session, platform="antigravity_cli")

    assert zip_path is not None, f"stage_agent_templates returned None: {msg}"
    assert zip_path.exists(), f"ZIP file not created at {zip_path}"

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        manifest_raw = zf.read("plugins/giljoai/plugin.json").decode("utf-8")

    # plugin.json exists at the nested path (not at root).
    assert "plugins/giljoai/plugin.json" in names, f"plugin.json missing from ZIP; entries: {names}"

    # At least one nested agent.json under plugins/giljoai/agents/.
    nested_agents = [n for n in names if n.startswith("plugins/giljoai/agents/") and n.endswith("/agent.json")]
    assert nested_agents, f"No nested agent.json found; entries: {names}"

    # Agents-only ZIP has NO skills/ (skills come via stage_combined_setup).
    # Critically: no BARE top-level skills/ or agents/ directories.
    assert not any(n.startswith(("skills/", "agents/")) for n in names), (
        f"Bare top-level skills/ or agents/ present (nesting guard regressed); entries: {names}"
    )

    # plugin.json is the minimal validator-accepted manifest {name, version, description}.
    manifest = json.loads(manifest_raw)
    assert set(manifest) == {"name", "version", "description"}, f"plugin.json has unexpected keys: {set(manifest)}"
    assert manifest["name"] == "giljoai"
