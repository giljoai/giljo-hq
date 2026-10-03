# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.dependencies.core import get_tenant_key
from giljo_mcp.tenant import current_tenant


def _request_without_tenant():
    return SimpleNamespace(method="GET", state=SimpleNamespace())


@pytest.mark.asyncio
async def test_saas_request_without_a_tenant_is_401(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.setenv("DEFAULT_TENANT_KEY", "tk_shared_default")
    token = current_tenant.set(None)
    try:
        with pytest.raises(HTTPException) as exc:
            await get_tenant_key(_request_without_tenant())
    finally:
        current_tenant.reset(token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ce_request_without_a_tenant_keeps_the_default_tenant(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "ce")
    monkeypatch.setenv("DEFAULT_TENANT_KEY", "tk_default_ce")
    token = current_tenant.set(None)
    try:
        assert await get_tenant_key(_request_without_tenant()) == "tk_default_ce"
    finally:
        current_tenant.reset(token)
