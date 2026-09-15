# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


_PLATFORMS = ["claude_code", "codex_cli", "opencode", "generic"]

_DELETED_COMMANDS = [
    "gil_get_agents",
    "gil-get-agents",
    "gil_add",
    "gil-add",
    "/gil_get",
    "$gil-get",
    "gil_chain",
    "gil-chain",
    "gil_get_reference",
]


@pytest.mark.parametrize("platform", _PLATFORMS)
async def test_bootstrap_prompt_advertises_giljo_not_legacy(api_client: AsyncClient, auth_headers: dict, platform: str):
    resp = await api_client.get(f"/api/download/bootstrap-prompt?platform={platform}", headers=auth_headers)
    assert resp.status_code == 200, f"{platform}: {resp.status_code} {resp.text}"

    prompt = resp.json()["prompt"]
    assert "giljo" in prompt.lower(), f"{platform} bootstrap prompt does not mention giljo"
    for legacy in _DELETED_COMMANDS:
        assert legacy not in prompt, f"{platform} bootstrap still advertises deleted command {legacy!r}"


async def test_bootstrap_prompt_for_opencode_installs_the_opencode_command_dir(
    api_client: AsyncClient, auth_headers: dict
):
    resp = await api_client.get("/api/download/bootstrap-prompt?platform=opencode", headers=auth_headers)
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    prompt = resp.json()["prompt"]
    assert "~/.config/opencode/commands/" in prompt
    assert "/giljo" in prompt
    assert "{SLASH_COMMANDS_URL}" not in prompt, "download URL placeholder was not substituted"


async def test_bootstrap_prompt_fails_closed_for_a_platform_without_a_template(
    api_client: AsyncClient, auth_headers: dict, monkeypatch
):
    from api.endpoints.downloads import bundles

    trimmed = {k: v for k, v in bundles._BOOTSTRAP_TEMPLATES.items() if k != "codex_cli"}
    monkeypatch.setattr(bundles, "_BOOTSTRAP_TEMPLATES", trimmed)
    resp = await api_client.get("/api/download/bootstrap-prompt?platform=codex_cli", headers=auth_headers)
    assert resp.status_code == 422, f"{resp.status_code} {resp.text}"
    body = resp.json()
    assert "codex_cli" in str(body)
    assert "claude_code" in str(body), "the rejection should name the platforms that do have a bootstrap"
