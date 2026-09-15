# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.asyncio


async def _make_taxonomy_type(api_client, auth_headers) -> str:
    resp = await api_client.post(
        "/api/v1/taxonomy-types/",
        headers=auth_headers,
        json={"abbreviation": "BE", "label": f"Backend {uuid.uuid4().hex[:6]}"},
    )
    assert resp.status_code == 201, f"taxonomy type setup failed: {resp.text}"
    return resp.json()["id"]


async def _make_product(api_client, auth_headers) -> str:
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"BE-9509 product {uuid.uuid4().hex[:6]}", "description": "no-active-product fixture"},
    )
    assert resp.status_code == 200, f"product setup failed: {resp.text}"
    product_id = resp.json()["id"]
    deactivate_resp = await api_client.post(f"/api/v1/products/{product_id}/deactivate", headers=auth_headers)
    assert deactivate_resp.status_code == 200, f"product deactivate failed: {deactivate_resp.text}"
    return product_id


async def _make_project(api_client, auth_headers, *, product_id, project_type_id, series_number, subseries=None):
    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={
            "name": f"BE-9509 fixture {uuid.uuid4().hex[:6]}",
            "description": "no-active-product fixture project",
            "product_id": product_id,
            "project_type_id": project_type_id,
            "series_number": series_number,
            "subseries": subseries,
        },
    )
    assert resp.status_code == 201, f"project setup failed: {resp.text}"
    return resp.json()


@pytest.fixture
async def cross_product_fixture(api_client, auth_headers):
    type_id = await _make_taxonomy_type(api_client, auth_headers)
    product_id = await _make_product(api_client, auth_headers)

    await _make_project(
        api_client, auth_headers, product_id=product_id, project_type_id=type_id, series_number=1, subseries=None
    )
    await _make_project(
        api_client, auth_headers, product_id=product_id, project_type_id=type_id, series_number=2, subseries="a"
    )

    return {"type_id": type_id, "product_id": product_id}


class TestNextSeriesNoActiveProduct:

    async def test_next_series_ignores_projects_in_a_real_non_active_product(
        self, api_client, auth_headers, cross_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/next-series",
            params={"type_id": cross_product_fixture["type_id"]},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"next_series_number": 1}


class TestAvailableSeriesNoActiveProduct:

    async def test_available_series_ignores_series_numbers_used_in_another_product(
        self, api_client, auth_headers, cross_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/available-series",
            params={"type_id": cross_product_fixture["type_id"], "limit": 5},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available_series_numbers": [1, 2, 3, 4, 5]}


class TestCheckSeriesNoActiveProduct:

    async def test_check_series_ignores_a_number_used_in_another_product(
        self, api_client, auth_headers, cross_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/check-series",
            params={"type_id": cross_product_fixture["type_id"], "series_number": 1},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available": True}

    async def test_check_series_control_an_unused_number_is_available(
        self, api_client, auth_headers, cross_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/check-series",
            params={"type_id": cross_product_fixture["type_id"], "series_number": 99},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available": True}


class TestUsedSubseriesNoActiveProduct:

    async def test_used_subseries_ignores_a_subseries_used_in_another_product(
        self, api_client, auth_headers, cross_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/used-subseries",
            params={"type_id": cross_product_fixture["type_id"], "series_number": 2},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"used_subseries": []}
