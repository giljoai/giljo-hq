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


_FILENAME = "giljo_setup.zip"
_ZIP_BYTES = b"PK\x03\x04 fake-but-non-empty zip payload for the regression test"


async def _seed_ready_token(db_manager) -> dict:
    tenant_key = TenantManager.generate_tenant_key()
    token = str(uuid.uuid4())

    async with db_manager.get_session_async() as session:
        session.add(
            DownloadToken(
                token=token,
                tenant_key=tenant_key,
                download_type="slash_commands",
                filename=_FILENAME,
                staging_status="ready",
                download_count=0,
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        await session.commit()

    staged_dir = Path.cwd() / "temp" / tenant_key / token
    staged_dir.mkdir(parents=True, exist_ok=True)
    (staged_dir / _FILENAME).write_bytes(_ZIP_BYTES)

    return {
        "tenant_key": tenant_key,
        "token": token,
        "url": f"/api/download/temp/{token}/{_FILENAME}",
        "tenant_dir": Path.cwd() / "temp" / tenant_key,
    }


@pytest_asyncio.fixture(scope="function")
async def staged_token(db_manager):
    seeded = await _seed_ready_token(db_manager)
    try:
        yield seeded
    finally:
        shutil.rmtree(seeded["tenant_dir"], ignore_errors=True)


@pytest.mark.asyncio
async def test_temp_download_returns_200_under_enforce_guard(
    api_client: AsyncClient, db_manager, staged_token: dict, monkeypatch
) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    resp = await api_client.get(staged_token["url"])

    assert resp.status_code == 200, resp.text
    assert resp.content == _ZIP_BYTES
    assert resp.headers["content-type"] == "application/zip"

    async with db_manager.get_session_async() as session:
        from sqlalchemy import select

        from giljo_mcp.database import tenant_session_context

        with tenant_session_context(session, staged_token["tenant_key"]):
            row = (
                await session.execute(select(DownloadToken).where(DownloadToken.token == staged_token["token"]))
            ).scalar_one()
        assert row.download_count == 1
        assert row.last_downloaded_at is not None


@pytest.mark.asyncio
async def test_temp_download_survives_metrics_failure(api_client: AsyncClient, staged_token: dict, monkeypatch) -> None:
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    from giljo_mcp.download_tokens import TokenManager

    async def _boom(self, token, tenant_key):  # noqa: ANN001 - test stub
        raise RuntimeError("simulated metrics backend failure")

    monkeypatch.setattr(TokenManager, "increment_download_count", _boom)

    resp = await api_client.get(staged_token["url"])

    assert resp.status_code == 200, resp.text
    assert resp.content == _ZIP_BYTES
