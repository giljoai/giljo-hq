# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest


@pytest.mark.asyncio
async def test_setup_status_unauthenticated_returns_200_under_enforce(api_client, monkeypatch):
    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    response = await api_client.get("/api/setup/status")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert "total_users_count" in data, (
        "Response is the fail-secure fallback, not the real signal — the "
        "contextless User count was swallowed instead of bypassed."
    )
    assert isinstance(data["total_users_count"], int)
    assert data["total_users_count"] >= 0
    assert "route_signal" in data
    assert "setup_complete" in data
