# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9326 regression: ``POST /api/v1/projects/`` succeeds without a project type.

The create endpoint used to hand the raw ``Project`` ORM row to the shared
``_to_project_response`` builder, which reads ``proj.project_type`` -- a plain
lazy ``relationship``. The service only eager-loaded that relationship when a
``project_type_id`` was supplied, so a create WITHOUT one committed the row,
closed the session, and then raised ``DetachedInstanceError`` while building the
response: the caller got a 500 and never learned the id of the project that had
in fact been created.

REACHABILITY: reachable by a real user, in first-run onboarding. The
Welcome-screen starter-template cards post exactly ``{name, description,
product_id}`` and no ``project_type_id``
(``frontend/src/views/WelcomeView.vue::createFromTemplate``; the store passes the
object straight through). Those cards render precisely in the brand-new-user
state -- setup complete, an active product, and zero projects -- so a user who
finished setup and clicked a starter template got this 500, and because
``createProject`` throws before its project refresh the cards stayed up and every
retry left another project behind. ``ProductForm.vue`` does send a
``project_type_id`` and took the eager-load branch, which is why the dashboard
looked unaffected -- it is simply not the only frontend path that creates a
project. REST/API integrations, scripts, and the QA harness hit it too.

Covered at the API layer because that is where the defect lived (the response
builder), not in the service.
"""

from __future__ import annotations

from uuid import uuid4

import pytest


pytestmark = pytest.mark.asyncio


async def _create_product(api_client, auth_headers) -> str:
    """Create a product to hang the project off (``product_id`` is required)."""
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"BE-9326 product {uuid4().hex[:8]}", "description": "regression fixture"},
    )
    assert resp.status_code == 200, f"product fixture failed: {resp.status_code}: {resp.text}"
    return resp.json()["id"]


async def test_create_project_without_project_type_id_returns_201(api_client, auth_headers):
    """The un-typed create must return 201 with a usable body -- not a 500 that
    hides the id of a row it already committed."""
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
    # The caller must learn the id of the row that was created -- that is the
    # whole point: every 500 here still left a project behind.
    assert body["id"]
    assert body["project_type_id"] is None
    assert body["project_type"] is None
    # column_property, computed by the SELECT -- present even with no type.
    assert "taxonomy_alias" in body


async def test_create_project_with_welcome_template_payload_returns_201(api_client, auth_headers):
    """The exact body the Welcome-screen starter templates send -- three keys,
    no ``project_type_id``.

    The test above covers "no project type" generically. This one pins the real
    dashboard payload so nobody re-derives the wrong reachability from the suite:
    ``WelcomeView.vue::createFromTemplate`` builds this object and
    ``stores/projects.js::createProject`` posts it unchanged, which the
    frontend's own spec asserts verbatim
    (``frontend/src/views/__tests__/WelcomeView.spec.js``, "calls
    projectStore.createProject with the verbatim template payload"). Whoever
    adds a fourth key here has changed what the dashboard sends, and should say
    so.
    """
    product_id = await _create_product(api_client, auth_headers)

    # Mirrors composables/projectTemplates.js -> WelcomeView.createFromTemplate.
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
    """The eager-load branch the dashboard takes must keep working, and must
    still emit the nested type info."""
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
