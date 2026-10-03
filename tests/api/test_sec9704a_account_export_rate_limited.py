# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.endpoints import tenant_data
from api.middleware import auth_rate_limiter
from api.middleware.auth_rate_limiter import RateLimiter


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/account/export",
            "headers": [(b"host", b"test")],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("203.0.113.9", 4000),
            "query_string": b"",
            "app": MagicMock(),
        }
    )


@pytest.mark.asyncio
async def test_a_fourth_export_inside_the_window_is_refused(monkeypatch, tmp_path, real_auth_rate_limiter):
    from giljo_mcp.services.cache_backends import reset_registry_for_tests

    reset_registry_for_tests()
    limiter = RateLimiter()
    monkeypatch.setattr(auth_rate_limiter, "get_rate_limiter", lambda: limiter)
    monkeypatch.setattr(tenant_data, "get_rate_limiter", lambda: limiter, raising=False)

    exports: list[str] = []

    class _Service:
        def __init__(self, **_kwargs):
            pass

        async def export(self, tenant_key):
            exports.append(tenant_key)
            path = tmp_path / f"export_{len(exports)}.zip"
            path.write_bytes(b"zip")
            return path, {}

    token_manager = MagicMock()
    token_manager.generate_token = AsyncMock(side_effect=lambda **_k: f"tok{len(exports)}")
    token_manager.mark_ready = AsyncMock()
    token_manager.get_token_info = AsyncMock(return_value=None)
    staging = MagicMock()
    staging.create_staging_directory = AsyncMock(side_effect=lambda tk, tok: _mkdir(tmp_path / tok))
    monkeypatch.setattr(tenant_data, "TenantExportService", _Service)
    monkeypatch.setattr("giljo_mcp.downloads.token_manager.TokenManager", lambda **_k: token_manager)
    monkeypatch.setattr("giljo_mcp.file_staging.FileStaging", lambda **_k: staging)
    user = MagicMock(tenant_key="tk_export_probe", username="u", role="admin")

    for _ in range(3):
        await tenant_data.export_tenant_data(_request(), current_user=user, db=MagicMock())
    with pytest.raises(HTTPException) as exc:
        await tenant_data.export_tenant_data(_request(), current_user=user, db=MagicMock())

    assert exc.value.status_code == 429
    assert len(exports) == 3


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
