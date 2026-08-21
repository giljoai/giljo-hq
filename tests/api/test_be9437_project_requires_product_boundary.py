# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9437 at the boundaries — a project without a product is REFUSED, never 500'd.

``projects.product_id`` has been NOT NULL in the database since ``ce_0004`` and
carries a foreign key to ``products``. Neither of those produces a usable error:
a caller who omits the product gets an IntegrityError surfaced as a 500, which
tells them nothing about what to send. The operator's 2026-08-15 ruling (a
project MUST belong to a product) is enforced here, where the caller can act on
it.

TWO LAYERS ON PURPOSE, and they answer different callers:

* ``ProjectCreate.product_id`` gains ``min_length=1``. Required-ness alone is not
  enough -- ``""`` satisfies a required ``str``, satisfies NOT NULL, and reaches
  the FK. This is the browser's answer and it is a 422 naming the field.
* ``ProjectService.create_project`` raises ``ValidationError``. This is the
  OWNING-SERVICE answer, and it is the one that matters for reach: REST,
  ``create_project_for_mcp`` and task conversion all funnel through this one
  method, so a caller that never touches the REST schema is still refused. It
  also catches whitespace-only, which ``min_length`` does not.

The layers land on different status codes (422 from the transport, 400 from the
service) and that is not an inconsistency worth flattening: both are actionable
refusals that name the field and neither is a 500, which is the whole point.
"""

from __future__ import annotations

import uuid

import pytest

from giljo_mcp.exceptions import ValidationError


pytestmark = pytest.mark.asyncio


class TestTheRestBoundaryRefusesAProductlessProject:
    async def test_an_empty_product_id_is_refused_and_not_a_500(self, api_client, auth_headers):
        """THE CASE REQUIRED-NESS ALONE MISSES.

        ``""`` is a valid required ``str`` and a valid NOT NULL value. Before
        BE-9437 it travelled all the way to the products foreign key and came
        back as a 500 with nothing the caller could act on.
        """
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
        """``min_length`` cannot see this one -- ``" "`` is one character. The
        owning-service guard is what refuses it, and it is still not a 500."""
        resp = await api_client.post(
            "/api/v1/projects/",
            headers=auth_headers,
            json={"name": "no product", "description": "boundary fixture", "product_id": "   "},
        )

        assert resp.status_code < 500, f"expected a refusal, got {resp.status_code}: {resp.text}"
        assert resp.status_code in (400, 422), f"expected a client error, got {resp.status_code}: {resp.text}"
        assert "product" in resp.text.lower()

    async def test_a_real_product_id_still_creates(self, api_client, auth_headers):
        """The control. Without it, a create endpoint that refused EVERYTHING
        would pass every assertion above.

        The product is created over HTTP rather than through the ``test_product``
        fixture: that fixture writes in the test's own session, and the app under
        ``api_client`` reads through a different connection, so the row is not
        there yet when the create runs -- which surfaces as the very FK 500 this
        module exists to rule out, from the wrong cause.
        """
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
    """The guard that reaches the callers no REST schema covers."""

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_create_project_refuses_a_missing_product(self, project_service_with_session, missing):
        with pytest.raises(ValidationError) as exc:
            await project_service_with_session.create_project(name="orphan", mission="", product_id=missing)

        message = str(exc.value)
        assert "product" in message.lower()
        assert "product_id" in message, "the message must name the parameter, not just the concept"

    async def test_create_project_accepts_a_real_product(self, project_service_with_session, test_product):
        """The control for the service layer, same reason as the REST one."""
        created = await project_service_with_session.create_project(
            name="bound", mission="", product_id=str(test_product.id)
        )

        assert created.product_id == str(test_product.id)


class TestProductIdCannotBeUnsetAfterCreation:
    """The 'patching a project to product_id NULL' half of the DoD.

    The finding worth recording is that there was nothing to ADD here.
    ``update_project`` applies only an explicit ``allowed_fields`` set, and
    ``product_id`` has never been in it -- so an update naming the field is
    dropped rather than applied, and the hole this project closes was never
    reachable from the update path. That is a property of the code, not a
    promise, so these tests exercise it end to end rather than reading the set.
    """

    async def test_an_update_cannot_null_out_the_product(
        self, project_service_with_session, test_product, test_tenant_key
    ):
        """The one that matters: a caller explicitly asking to clear the binding
        is ignored, not obeyed."""
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
        """The same door, one step further open. Re-homing a project is not a
        rename: the destination product has its own single-active and taxonomy
        constraints, so it would need its own decision and its own validation.
        Today it is simply not reachable, and this pins that."""
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
        """The transport half. If someone adds the field here, they meet this
        test before they meet the indexes on the destination product."""
        from api.endpoints.projects.models import ProjectUpdate

        assert "product_id" not in ProjectUpdate.model_fields, (
            "ProjectUpdate gained a product_id field. A project's product is set at creation "
            "(BE-9437); letting an update rewrite or clear it needs its own decision, its own "
            "tenant-ownership validation, and its own handling of the single-active and "
            "taxonomy indexes on the destination product."
        )
