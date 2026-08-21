# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9215 regression: product/project ``name`` is capped at 255 chars.

The ``products.name`` and ``projects.name`` columns are ``String(255)``. Before
this fix the browser create/edit flows had no length validation, so a >255-char
name reached the DB and raised a raw ``StringDataRightTruncation`` -> uncontrolled
500 instead of a clean 422.

Tests exercise BOTH transports at the layer each was broken:

* REST/browser boundary (``api_client``): create AND edit, for products AND
  projects, with a 300-char name -> 422 (Pydantic ``max_length``), never a 500.
* Owning-service funnel (``ProjectService`` / ``ProductService``): the same
  over-long name -> a clean ``ValidationError`` (mapped to 422 at the MCP
  boundary). This is the shared write path behind ``create_project_for_mcp`` /
  ``create_product`` (the agent transport), so a service-layer cap closes it for
  every caller, not just the REST forms.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.product_service import ProductService


pytestmark = pytest.mark.asyncio

_OVER_LIMIT = "x" * 300  # > 255, and well over the 200 the MCP adapter caps at


def _unique_name_at_255() -> str:
    """A name exactly 255 chars long but unique per call (xdist-safe: the
    create path enforces per-tenant name uniqueness)."""
    suffix = uuid4().hex  # 32 chars
    return suffix + "y" * (255 - len(suffix))


# ---------------------------------------------------------------------------
# REST / browser boundary — the layer the user hit (must 422, not 500)
# ---------------------------------------------------------------------------


async def test_product_create_over_255_name_returns_422(api_client, auth_headers):
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": _OVER_LIMIT, "description": "regression fixture"},
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
    assert "255" in resp.text


async def test_product_update_over_255_name_returns_422(api_client, auth_headers):
    # Pydantic body validation fires before the row lookup, so a random id is fine.
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
    """The boundary value (exactly 255) must still succeed — the cap is inclusive."""
    name = _unique_name_at_255()
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": name, "description": "boundary fixture"},
    )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["name"] == name


# ---------------------------------------------------------------------------
# Owning-service funnel — the agent (MCP) transport's write path
# ---------------------------------------------------------------------------


async def test_project_service_create_over_255_raises(project_service_with_session):
    """create_project (the funnel behind create_project_for_mcp) rejects >255."""
    with pytest.raises(ValidationError) as exc:
        await project_service_with_session.create_project(name=_OVER_LIMIT, mission="")
    assert "255" in str(exc.value)


async def test_project_service_update_over_255_raises(project_service_with_session, test_product):
    # BE-9437: product_id is required, so the row this test updates needs a real
    # product. The cap under test is on ``name`` and is unaffected by the binding.
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
