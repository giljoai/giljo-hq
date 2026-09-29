# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio

_PATH_SENTINEL = "/opt/giljo/temp/tk_abc123/secrettoken/slash_commands.zip"


async def test_generate_token_staging_failure_carries_no_absolute_path(
    api_client: AsyncClient, auth_headers: dict, monkeypatch
):
    from giljo_mcp.file_staging import FileStaging

    async def _boom(self, staging_path, platform="claude_code"):
        return (None, f"Disk error creating slash commands ZIP: [Errno 28] No space left: '{_PATH_SENTINEL}'")

    monkeypatch.setattr(FileStaging, "stage_slash_commands", _boom)

    resp = await api_client.post("/api/download/generate-token?content_type=slash_commands", headers=auth_headers)

    assert resp.status_code == 500, f"{resp.status_code} {resp.text}"
    assert _PATH_SENTINEL not in resp.text, f"absolute staging path leaked into the 500 body: {resp.text}"


async def test_bootstrap_prompt_staging_failure_carries_no_absolute_path(
    api_client: AsyncClient, auth_headers: dict, monkeypatch
):
    from giljo_mcp.file_staging import FileStaging

    async def _boom(self, staging_path, platform="claude_code"):
        return (None, f"Disk error creating slash commands ZIP: [Errno 28] No space left: '{_PATH_SENTINEL}'")

    monkeypatch.setattr(FileStaging, "stage_slash_commands", _boom)

    resp = await api_client.get("/api/download/bootstrap-prompt?platform=claude_code", headers=auth_headers)

    assert resp.status_code == 500, f"{resp.status_code} {resp.text}"
    assert _PATH_SENTINEL not in resp.text, f"absolute staging path leaked into the 500 body: {resp.text}"
