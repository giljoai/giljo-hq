# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9509 / BE-9515: pin the four ``api/endpoints/projects/series.py``
endpoints on the NO-ACTIVE-PRODUCT path (BE-9502a follow-up).

These four endpoints resolve the active product as a fallback (``product_id =
active_product.id if active_product else None``), and none of them had a
REST-level test for the "no active product" branch. Active-product is being
demoted from server truth to a default, so behaviour must be pinned before it
changes.

BE-9509 pinned the four endpoints' behaviour as found, INCLUDING a genuine
asymmetry: ``get_next_series_number`` applied ``product_id`` UNCONDITIONALLY,
scoping a ``None`` product to the ``product_id IS NULL`` bucket, while
``get_used_series_numbers`` / ``check_series_available`` /
``get_used_subseries`` applied it only ``if product_id is not None``.

**BE-9515: that asymmetry is a defect, not a spec, and has been fixed.** All
four endpoints now apply ``product_id`` UNCONDITIONALLY, matching
``get_next_series_number``. The assertions below that captured the old
behaviour are therefore INVERTED rather than deleted, so the history stays
traceable. Each inversion is marked "BE-9515: inverted from BE-9509" with the
original expectation noted alongside.
"""

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
    # FE-9524/D1: a new product is shown/active by default now -- this
    # module's entire premise is the NO-active-product fallback path, so the
    # product must be explicitly hidden to keep that precondition true.
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
    """Two projects in a REAL (non-active) product -- no product in this
    tenant is ever activated, so ``get_default_product()`` returns ``None``
    for every request in this module.

    ``series_number=1, subseries=None`` and ``series_number=2, subseries='a'``
    give ``check-series``/``available-series`` and ``used-subseries``
    respectively something to find IF the no-active-product path treats the
    tenant as unscoped -- and nothing to find now that it is correctly
    isolated to a null-product bucket (BE-9515).
    """
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
    """GET /next-series pins to the ``product_id IS NULL`` bucket (BE-6079 M1).

    Unaffected by BE-9515 -- this endpoint was always correct and is the
    behaviour the other three were aligned to.
    """

    async def test_next_series_ignores_projects_in_a_real_non_active_product(
        self, api_client, auth_headers, cross_product_fixture
    ):
        """A project sitting in a real product must NOT inflate the
        null-product watermark just because no product is active."""
        resp = await api_client.get(
            "/api/v1/projects/next-series",
            params={"type_id": cross_product_fixture["type_id"]},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"next_series_number": 1}


class TestAvailableSeriesNoActiveProduct:
    """GET /available-series -- BE-9515: inverted from BE-9509.

    Original (leaking) expectation: ``[3, 4, 5, 6, 7]`` -- series 1 and 2
    from the OTHER product were treated as used, so the gap-filling walk
    skipped past them. Now that ``product_id`` is applied unconditionally,
    the null-product bucket is empty and the walk starts at 1.
    """

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
    """GET /check-series -- BE-9515: inverted from BE-9509.

    Original (leaking) expectation for series_number=1: ``{"available": False}``
    -- unavailable only because a DIFFERENT product had used it. Now scoped
    to the null-product bucket, it is available.
    """

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
        """The control: without the fix, a check-series that always returned
        ``True`` would pass the assertion above too."""
        resp = await api_client.get(
            "/api/v1/projects/check-series",
            params={"type_id": cross_product_fixture["type_id"], "series_number": 99},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"available": True}


class TestUsedSubseriesNoActiveProduct:
    """GET /used-subseries -- BE-9515: inverted from BE-9509.

    Original (leaking) expectation: ``["a"]`` -- the subseries from the
    OTHER product's series_number=2 project leaked in. Now scoped to the
    null-product bucket, there is nothing there.
    """

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
