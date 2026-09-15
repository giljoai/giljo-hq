# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import zipfile

import pytest

from giljo_mcp.file_staging import FileStaging
from giljo_mcp.platform_registry import EXPORT_PLATFORMS
from giljo_mcp.tools.setup_instructions import ProductBindingContext, build_setup_instructions


_AGENT_INSTALL_MARKERS = (
    "Agents only",
    "INSTALL_AGENTS",
    "AGENTS_INSTALLED",
    "giljo-managed:",
    "agents/",
    "[agents.gil-",
    "gil-*.toml",
    "Choose install scope",
    "HTTP 410",
)


@pytest.mark.parametrize("platform", EXPORT_PLATFORMS)
@pytest.mark.asyncio
async def test_setup_bundle_contains_only_skill_or_command_entries(tmp_path, platform):
    staging = FileStaging(base_path=tmp_path)
    zip_path, message = await staging.stage_setup_bundle(tmp_path / "s", platform=platform)
    assert zip_path is not None, message
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert names, "bundle must still carry the skills / commands"
    offenders = [n for n in names if not n.startswith(("skills/", "commands/"))]
    assert offenders == [], f"{platform}: agent-looking entries in the setup bundle: {offenders}"
    assert not any(n.endswith(".toml") for n in names), names


@pytest.mark.parametrize("platform", EXPORT_PLATFORMS)
@pytest.mark.parametrize("harness", [None, "claude_code", "codex_cli", "opencode", "desktop_app"])
def test_install_prose_never_mentions_agent_files(platform, harness):
    prose = build_setup_instructions(
        platform,
        "https://example.test/api/download/temp/tok/giljo_setup.zip",
        harness,
        product_binding=ProductBindingContext(phase="bound", product_id="p1", product_name="P"),
    )
    hits = [m for m in _AGENT_INSTALL_MARKERS if m in prose]
    assert hits == [], f"{platform}/{harness}: agent-install prose survived: {hits}"
    assert "GILJO_PRODUCT_BINDING_START" in prose, "marker block must stay"
    assert "GILJOAI_MCP_PRIMER_START" in prose, "primer block must stay"
    assert "agent_profile" in prose or "job starts" in prose, "prose must say where profiles now come from"


def test_file_staging_has_no_agent_export_surface():
    for name in ("stage_agent_templates", "stage_combined_setup"):
        assert not hasattr(FileStaging, name), f"FileStaging.{name} must be gone"
    import giljo_mcp.file_staging as mod

    assert not hasattr(mod, "staged_agent_zip_is_stale")
    assert not hasattr(mod, "_codex_agents_to_toml")
