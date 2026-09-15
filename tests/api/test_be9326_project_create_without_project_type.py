# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest


pytestmark = pytest.mark.asyncio


async def _create_product(api_client, auth_headers) -> str:
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"BE-9326 product {uuid4().hex[:8]}", "description": "regression fixture"},
    )
    assert resp.status_code == 200, f"product fixture failed: {resp.status_code}: {resp.text}"
    return resp.json()["id"]


async def test_create_project_without_project_type_id_returns_201(api_client, auth_headers):
    product_id = await _create_product(api_client, auth_headers)

    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={
            "name": f"BE-9326 untyped project {uuid4().hex[:8]}",
            "description": "created with no project_type_id",
            "product_id": product_id,
        },
    )

    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["id"]
    assert body["project_type_id"] is None
    assert body["project_type"] is None
    assert "taxonomy_alias" in body


async def test_create_project_with_welcome_template_payload_returns_201(api_client, auth_headers):
    product_id = await _create_product(api_client, auth_headers)

    payload = {
        "name": f"Initiate new product (starter) {uuid4().hex[:8]}",
        "description": "Starter template project created from the Welcome screen.",
        "product_id": product_id,
    }
    assert set(payload) == {"name", "description", "product_id"}, (
        "this test only means something while it posts the verbatim three-key Welcome-template body"
    )

    resp = await api_client.post("/api/v1/projects/", headers=auth_headers, json=payload)

    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["id"]
    assert body["name"] == payload["name"]
    assert body["project_type_id"] is None
    assert body["project_type"] is None


async def test_create_project_with_project_type_id_still_returns_201(api_client, auth_headers):
    product_id = await _create_product(api_client, auth_headers)

    types_resp = await api_client.get("/api/v1/taxonomy-types/", headers=auth_headers)
    assert types_resp.status_code == 200, f"{types_resp.status_code}: {types_resp.text}"
    project_types = types_resp.json()
    if not project_types:
        pytest.skip(reason="no seeded project types for this tenant")
    project_type_id = project_types[0]["id"]

    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={
            "name": f"BE-9326 typed project {uuid4().hex[:8]}",
            "description": "created with a project_type_id",
            "product_id": product_id,
            "project_type_id": project_type_id,
        },
    )

    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["project_type_id"] == project_type_id
    assert body["project_type"] is not None
    assert body["project_type"]["id"] == project_type_id
