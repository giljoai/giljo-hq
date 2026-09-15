# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService


pytestmark = pytest.mark.asyncio

_OVER_LIMIT = "x" * 300


def _unique_name_at_255() -> str:
    suffix = uuid4().hex
    return suffix + "y" * (255 - len(suffix))




async def test_product_create_over_255_name_returns_422(api_client, auth_headers):
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": _OVER_LIMIT, "description": "regression fixture"},
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    assert "255" in resp.text


async def test_product_update_over_255_name_returns_422(api_client, auth_headers):
    resp = await api_client.put(
        f"/api/v1/products/{uuid4()}",
        headers=auth_headers,
        json={"name": _OVER_LIMIT},
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    assert "255" in resp.text


async def test_project_create_over_255_name_returns_422(api_client, auth_headers):
    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={"name": _OVER_LIMIT, "description": "regression fixture", "product_id": str(uuid4())},
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    assert "255" in resp.text


async def test_project_update_over_255_name_returns_422(api_client, auth_headers):
    resp = await api_client.patch(
        f"/api/v1/projects/{uuid4()}",
        headers=auth_headers,
        json={"name": _OVER_LIMIT},
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    assert "255" in resp.text


async def test_product_create_at_255_name_is_accepted(api_client, auth_headers):
    name = _unique_name_at_255()
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": name, "description": "boundary fixture"},
    )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["name"] == name




async def test_project_service_create_over_255_raises(project_service_with_session):
    with pytest.raises(ValidationError) as exc:
        await project_service_with_session.create_project(name=_OVER_LIMIT, mission="")
    assert "255" in str(exc.value)


async def test_project_service_update_over_255_raises(project_service_with_session, test_product):
    created = await project_service_with_session.create_project(
        name="valid name", mission="", product_id=test_product.id
    )
    with pytest.raises(ValidationError) as exc:
        await project_service_with_session.update_project(created.id, {"name": _OVER_LIMIT})
    assert "255" in str(exc.value)


async def test_product_service_create_over_255_raises(db_manager, db_session, test_tenant_key):
    service = ProductService(db_manager=db_manager, tenant_key=test_tenant_key, test_session=db_session)
    with pytest.raises(ValidationError) as exc:
        await service.create_product(name=_OVER_LIMIT)
    assert "255" in str(exc.value)


async def test_product_service_update_over_255_raises(db_manager, db_session, test_tenant_key):
    service = ProductService(db_manager=db_manager, tenant_key=test_tenant_key, test_session=db_session)
    with pytest.raises(ValidationError) as exc:
        await service.update_product(str(uuid4()), name=_OVER_LIMIT)
    assert "255" in str(exc.value)
