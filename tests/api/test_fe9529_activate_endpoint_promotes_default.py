# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
FE-9529 -- REST-boundary pin for the
activate-promotes-implicit-default fix.

ProductLifecycleService.activate_product is the ONE owning writer behind
``POST /api/v1/products/{id}/activate`` -- the dual-door rule means any
caller of that endpoint (dashboard, a script, a future MCP tool) must get the
same "the sole-shown product's implicit default survives showing a second
product" guarantee. The service-layer tests
(tests/services/test_fe9529_activate_promotes_implicit_default.py) already
cover the transition logic directly; this test hits the REST endpoint itself,
bypassing the frontend store entirely, to prove the fix lives at the layer
every caller shares -- exactly the design a store-only fix would have missed.

Edition scope: Both.
"""

from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.asyncio


async def _make_product(api_client, auth_headers) -> str:
    """A new product is shown (is_active=True) by default (FE-9524/D1)."""
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"FE-9529 product {uuid.uuid4().hex[:6]}", "description": "activate-promotes-default fixture"},
    )
    assert resp.status_code == 200, f"product setup failed: {resp.text}"
    return resp.json()["id"]


async def test_activate_endpoint_promotes_sole_shown_products_implicit_default(api_client, auth_headers):
    """
    Product A: created shown, is_default never set explicitly. Product B:
    created shown (default), then hidden so A is the tenant's SOLE shown
    product with a fallback-only default. Activating B via the REST endpoint
    directly (no frontend store involved) must persist A's default before
    the transition that would otherwise erase the fallback.
    """
    product_a = await _make_product(api_client, auth_headers)
    product_b = await _make_product(api_client, auth_headers)

    hide_resp = await api_client.post(f"/api/v1/products/{product_b}/deactivate", headers=auth_headers)
    assert hide_resp.status_code == 200, f"hiding B failed: {hide_resp.text}"

    before = await api_client.get(f"/api/v1/products/{product_a}", headers=auth_headers)
    assert before.status_code == 200
    assert before.json()["is_default"] is False, "precondition: A's default is still only the sole-shown fallback"

    activate_resp = await api_client.post(f"/api/v1/products/{product_b}/activate", headers=auth_headers)
    assert activate_resp.status_code == 200, f"activating B failed: {activate_resp.text}"

    after_a = await api_client.get(f"/api/v1/products/{product_a}", headers=auth_headers)
    assert after_a.status_code == 200
    assert after_a.json()["is_default"] is True, (
        "the sole-shown product's implicit default must be persisted before a second product is shown"
    )

    after_b = await api_client.get(f"/api/v1/products/{product_b}", headers=auth_headers)
    assert after_b.status_code == 200
    assert after_b.json()["is_default"] is False, "showing B must not itself become the default"

    refresh_resp = await api_client.get("/api/v1/products/refresh-active", headers=auth_headers)
    assert refresh_resp.status_code == 200
    refreshed = refresh_resp.json()
    assert refreshed["has_active_product"] is True
    assert refreshed["product"]["id"] == product_a, "the resolved default now survives both products being shown"
