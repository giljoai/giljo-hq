# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from giljo_mcp.tenant import current_tenant


def _tenant_key_of(auth_headers: dict) -> str:
    token = auth_headers["Cookie"].split("access_token=")[1].split(";")[0]
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["tenant_key"]


@pytest.mark.asyncio
async def test_coverage_target_zero_survives_rest_and_context_reads(api_client, auth_headers, db_manager):
    from giljo_mcp.tools.context_tools.get_testing import get_testing

    created = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"G7 {uuid4().hex[:6]}", "description": "d", "test_config": {"coverage_target": 0}},
    )
    assert created.status_code == 200, created.text
    product_id = created.json()["id"]

    detail = await api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["test_config"]["coverage_target"] == 0

    tenant_key = _tenant_key_of(auth_headers)
    token = current_tenant.set(tenant_key)
    try:
        context = await get_testing(product_id=product_id, tenant_key=tenant_key, db_manager=db_manager)
    finally:
        current_tenant.reset(token)
    assert context["data"]["coverage_target"] == 0
