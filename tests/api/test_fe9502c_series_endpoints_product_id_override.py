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
        json={"name": f"FE-9502c product {uuid.uuid4().hex[:6]}", "description": "product_id override fixture"},
    )
    assert resp.status_code == 200, f"product setup failed: {resp.text}"
    return resp.json()["id"]


async def _make_project(api_client, auth_headers, *, product_id, project_type_id, series_number, subseries=None):
    resp = await api_client.post(
        "/api/v1/projects/",
        headers=auth_headers,
        json={
            "name": f"FE-9502c fixture {uuid.uuid4().hex[:6]}",
            "description": "product_id override fixture project",
            "product_id": product_id,
            "project_type_id": project_type_id,
            "series_number": series_number,
            "subseries": subseries,
        },
    )
    assert resp.status_code == 201, f"project setup failed: {resp.text}"
    return resp.json()


@pytest.fixture
async def two_product_fixture(api_client, auth_headers):
    type_id = await _make_taxonomy_type(api_client, auth_headers)
    product_a = await _make_product(api_client, auth_headers)
    product_b = await _make_product(api_client, auth_headers)

    await _make_project(
        api_client, auth_headers, product_id=product_a, project_type_id=type_id, series_number=1, subseries=None
    )
    await _make_project(
        api_client, auth_headers, product_id=product_a, project_type_id=type_id, series_number=2, subseries="a"
    )

    activate_resp = await api_client.post(f"/api/v1/products/{product_b}/activate", headers=auth_headers)
    assert activate_resp.status_code == 200, f"activation setup failed: {activate_resp.text}"

    return {"type_id": type_id, "product_a": product_a, "product_b": product_b}


class TestNextSeriesProductIdOverride:
    async def test_resolves_against_the_overridden_product_not_the_active_one(
        self, api_client, auth_headers, two_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/next-series",
            params={"type_id": two_product_fixture["type_id"], "product_id": two_product_fixture["product_a"]},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"next_series_number": 3}


class TestAvailableSeriesProductIdOverride:
    async def test_resolves_against_the_overridden_product_not_the_active_one(
        self, api_client, auth_headers, two_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/available-series",
            params={
                "type_id": two_product_fixture["type_id"],
                "limit": 5,
                "product_id": two_product_fixture["product_a"],
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available_series_numbers": [3, 4, 5, 6, 7]}


class TestCheckSeriesProductIdOverride:
    async def test_a_number_used_in_the_overridden_product_is_unavailable(
        self, api_client, auth_headers, two_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/check-series",
            params={
                "type_id": two_product_fixture["type_id"],
                "series_number": 1,
                "product_id": two_product_fixture["product_a"],
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available": False}

    async def test_control_an_unused_number_in_the_overridden_product_is_available(
        self, api_client, auth_headers, two_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/check-series",
            params={
                "type_id": two_product_fixture["type_id"],
                "series_number": 99,
                "product_id": two_product_fixture["product_a"],
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available": True}


class TestAvailableSeriesLimitBound:

    async def test_oversized_limit_is_rejected(self, api_client, auth_headers):
        type_id = await _make_taxonomy_type(api_client, auth_headers)

        resp = await api_client.get(
            "/api/v1/projects/available-series",
            params={"type_id": type_id, "limit": 100_000},
            headers=auth_headers,
        )

        assert resp.status_code == 422, resp.text


class TestUsedSubseriesProductIdOverride:
    async def test_resolves_against_the_overridden_product_not_the_active_one(
        self, api_client, auth_headers, two_product_fixture
    ):
        resp = await api_client.get(
            "/api/v1/projects/used-subseries",
            params={
                "type_id": two_product_fixture["type_id"],
                "series_number": 2,
                "product_id": two_product_fixture["product_a"],
            },
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"used_subseries": ["a"]}
