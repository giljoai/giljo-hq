# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.exceptions import ValidationError


pytestmark = pytest.mark.asyncio


class TestTheRestBoundaryRefusesAProductlessProject:
    async def test_an_empty_product_id_is_refused_and_not_a_500(self, api_client, auth_headers):
        resp = await api_client.post(
            "/api/v1/projects/",
            headers=auth_headers,
            json={"name": "no product", "description": "boundary fixture", "product_id": ""},
        )

        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
        assert resp.status_code < 500, "an empty product_id must never surface as a server error"
        assert "product_id" in resp.text, "the refusal must name the field the caller has to fix"

    async def test_an_omitted_product_id_is_refused(self, api_client, auth_headers):
        resp = await api_client.post(
            "/api/v1/projects/",
            headers=auth_headers,
            json={"name": "no product", "description": "boundary fixture"},
        )

        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"
        assert "product_id" in resp.text

    async def test_a_whitespace_only_product_id_is_refused_by_the_service(self, api_client, auth_headers):
        resp = await api_client.post(
            "/api/v1/projects/",
            headers=auth_headers,
            json={"name": "no product", "description": "boundary fixture", "product_id": "   "},
        )

        assert resp.status_code < 500, f"expected a refusal, got {resp.status_code}: {resp.text}"
        assert resp.status_code in (400, 422), f"expected a client error, got {resp.status_code}: {resp.text}"
        assert "product" in resp.text.lower()

    async def test_a_real_product_id_still_creates(self, api_client, auth_headers):
        product_resp = await api_client.post(
            "/api/v1/products/",
            headers=auth_headers,
            json={"name": f"BE-9437 product {uuid.uuid4().hex[:6]}", "description": "boundary fixture"},
        )
        assert product_resp.status_code == 200, f"product setup failed: {product_resp.text}"
        product_id = product_resp.json()["id"]

        resp = await api_client.post(
            "/api/v1/projects/",
            headers=auth_headers,
            json={
                "name": f"real product {uuid.uuid4().hex[:6]}",
                "description": "boundary fixture",
                "product_id": product_id,
            },
        )

        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        assert resp.json()["product_id"] == product_id


class TestTheOwningServiceRefusesEveryCaller:

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_create_project_refuses_a_missing_product(self, project_service_with_session, missing):
        with pytest.raises(ValidationError) as exc:
            await project_service_with_session.create_project(name="orphan", mission="", product_id=missing)

        message = str(exc.value)
        assert "product" in message.lower()
        assert "product_id" in message, "the message must name the parameter, not just the concept"

    async def test_create_project_accepts_a_real_product(self, project_service_with_session, test_product):
        created = await project_service_with_session.create_project(
            name="bound", mission="", product_id=str(test_product.id)
        )

        assert created.product_id == str(test_product.id)


class TestProductIdCannotBeUnsetAfterCreation:

    async def test_an_update_cannot_null_out_the_product(
        self, project_service_with_session, test_product, test_tenant_key
    ):
        created = await project_service_with_session.create_project(
            name=f"bound {uuid.uuid4().hex[:6]}", mission="", product_id=str(test_product.id)
        )

        await project_service_with_session.update_project(created.id, {"product_id": None, "name": "renamed"})

        after = await project_service_with_session.get_project(created.id, test_tenant_key)
        assert after.product_id == str(test_product.id), "update_project must not be able to orphan a project"
        assert after.name == "renamed", "the control -- the update itself did happen"

    async def test_an_update_cannot_move_a_project_to_another_product(
        self, project_service_with_session, test_product, db_session, test_tenant_key
    ):
        from giljo_mcp.models.products import Product

        other = Product(
            id=str(uuid.uuid4()),
            name=f"Other {uuid.uuid4().hex[:6]}",
            description="destination",
            tenant_key=test_tenant_key,
            is_active=False,
        )
        db_session.add(other)
        await db_session.commit()

        created = await project_service_with_session.create_project(
            name=f"bound {uuid.uuid4().hex[:6]}", mission="", product_id=str(test_product.id)
        )

        await project_service_with_session.update_project(created.id, {"product_id": other.id})

        after = await project_service_with_session.get_project(created.id, test_tenant_key)
        assert after.product_id == str(test_product.id)

    async def test_the_rest_update_model_has_no_product_id(self):
        from api.endpoints.projects.models import ProjectUpdate

        assert "product_id" not in ProjectUpdate.model_fields, (
            "ProjectUpdate gained a product_id field. A project's product is set at creation "
            "(BE-9437); letting an update rewrite or clear it needs its own decision, its own "
            "tenant-ownership validation, and its own handling of the single-active and "
            "taxonomy indexes on the destination product."
        )
