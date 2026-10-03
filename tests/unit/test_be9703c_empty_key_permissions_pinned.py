# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest


def _resolved(permissions):
    key = SimpleNamespace(name="k", tenant_key="tk_pinned", permissions=permissions)
    return key, SimpleNamespace(id="u1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected"),
    [([], ["*"]), (None, ["*"]), (["projects:read"], ["projects:read"])],
)
async def test_websocket_api_key_permissions_today(monkeypatch, stored, expected):
    from api import auth_utils
    from giljo_mcp.auth import principal

    async def _fake_resolve(db, api_key):
        return _resolved(stored)

    monkeypatch.setattr(principal, "_resolve_api_key", _fake_resolve)
    result = await auth_utils.validate_api_key("gk_anything", db=object())
    assert result["permissions"] == expected


@pytest.mark.asyncio
async def test_auth_manager_api_key_result_defaults_missing_permissions_to_everything():
    from giljo_mcp.auth_manager import AuthManager

    manager = AuthManager.__new__(AuthManager)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_manager=None)))
    result = await manager._build_api_key_result({"name": "k", "tenant_key": "tk_pinned"}, request)
    assert result["permissions"] == ["*"]
