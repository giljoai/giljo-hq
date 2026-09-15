# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient

from giljo_mcp.models import DownloadToken
from giljo_mcp.tenant import TenantManager


_ZIP_BYTES = b"PK\x03\x04 fake-but-non-empty zip payload for the regression test"


class _RecordingWsManager:

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def broadcast_event_to_tenant(self, *, tenant_key: str, event: dict) -> None:  # noqa: ARG002
        self.events.append(event)


def _event_types(ws: _RecordingWsManager) -> list[str]:
    return [e.get("type") or e.get("event_type") for e in ws.events]


async def _seed_ready_token(db_manager, filename: str) -> dict:
    tenant_key = TenantManager.generate_tenant_key()
    token = str(uuid.uuid4())

    async with db_manager.get_session_async() as session:
        session.add(
            DownloadToken(
                token=token,
                tenant_key=tenant_key,
                download_type="slash_commands",
                filename=filename,
                staging_status="ready",
                download_count=0,
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        await session.commit()

    staged_dir = Path.cwd() / "temp" / tenant_key / token
    staged_dir.mkdir(parents=True, exist_ok=True)
    (staged_dir / filename).write_bytes(_ZIP_BYTES)

    return {
        "tenant_key": tenant_key,
        "token": token,
        "filename": filename,
        "url": f"/api/download/temp/{token}/{filename}",
        "tenant_dir": Path.cwd() / "temp" / tenant_key,
    }


@pytest_asyncio.fixture(scope="function")
async def recording_ws():
    from api.app import app

    prior = getattr(app.state, "websocket_manager", None)
    ws = _RecordingWsManager()
    app.state.websocket_manager = ws
    try:
        yield ws
    finally:
        app.state.websocket_manager = prior


@pytest.mark.asyncio
async def test_setup_bundle_zip_emits_commands_installed(
    api_client: AsyncClient, db_manager, recording_ws: _RecordingWsManager
) -> None:
    seeded = await _seed_ready_token(db_manager, "giljo_setup.zip")
    try:
        resp = await api_client.get(seeded["url"])
        assert resp.status_code == 200, resp.text
        assert resp.content == _ZIP_BYTES

        types = _event_types(recording_ws)
        assert "setup:commands_installed" in types, types

        evt = next(e for e in recording_ws.events if (e.get("type") == "setup:commands_installed"))
        assert evt["data"]["tenant_key"] == seeded["tenant_key"]
    finally:
        shutil.rmtree(seeded["tenant_dir"], ignore_errors=True)


@pytest.mark.asyncio
async def test_slash_commands_zip_still_emits_commands(
    api_client: AsyncClient, db_manager, recording_ws: _RecordingWsManager
) -> None:
    seeded = await _seed_ready_token(db_manager, "slash_commands.zip")
    try:
        resp = await api_client.get(seeded["url"])
        assert resp.status_code == 200, resp.text

        types = _event_types(recording_ws)
        assert "setup:commands_installed" in types, types
    finally:
        shutil.rmtree(seeded["tenant_dir"], ignore_errors=True)
