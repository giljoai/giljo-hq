# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest


def _tenant_key_of(auth_headers: dict) -> str:
    token = auth_headers["Cookie"].split("access_token=")[1].split(";")[0]
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _project(api_client, auth_headers) -> str:
    product = await api_client.post(
        "/api/v1/products/", headers=auth_headers, json={"name": f"G2 {uuid4().hex[:6]}", "description": "d"}
    )
    assert product.status_code == 200, product.text
    project = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={"name": f"G2 project {uuid4().hex[:6]}", "description": "d", "product_id": product.json()["id"]},
    )
    assert project.status_code in (200, 201), project.text
    return project.json()["id"]


@pytest.mark.asyncio
async def test_unknown_sort_key_is_422(api_client, auth_headers):
    response = await api_client.get("/api/v1/projects/", headers=auth_headers, params={"sort": "bogus", "limit": 5})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_unknown_sort_dir_is_422(api_client, auth_headers):
    response = await api_client.get(
        "/api/v1/projects/", headers=auth_headers, params={"sort": "name", "sort_dir": "sideways", "limit": 5}
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_purge_reports_the_real_tenant_key(api_client, auth_headers):
    project_id = await _project(api_client, auth_headers)
    soft = await api_client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert soft.status_code == 200, soft.text
    purge = await api_client.delete(f"/api/v1/projects/{project_id}/purge", headers=auth_headers)
    assert purge.status_code == 200, purge.text
    entry = purge.json()["projects"][0]
    assert entry["tenant_key"] == _tenant_key_of(auth_headers)
    assert "deleted_at" not in entry or entry["deleted_at"] is None
