# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["check-series", "used-subseries"])
async def test_five_digit_serial_lookup_is_not_422(api_client: AsyncClient, auth_headers: dict, path: str) -> None:
    resp = await api_client.get(
        f"/api/v1/projects/{path}",
        params={"series_number": 10000},
        headers=auth_headers,
    )
    assert resp.status_code != 422, resp.text
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["check-series", "used-subseries"])
async def test_six_digit_upper_bound_still_enforced(api_client: AsyncClient, auth_headers: dict, path: str) -> None:
    resp = await api_client.get(
        f"/api/v1/projects/{path}",
        params={"series_number": 1000000},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["check-series", "used-subseries"])
async def test_zero_lower_bound_still_enforced(api_client: AsyncClient, auth_headers: dict, path: str) -> None:
    resp = await api_client.get(
        f"/api/v1/projects/{path}",
        params={"series_number": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
