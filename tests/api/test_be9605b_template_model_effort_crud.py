# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def product_id(api_client, auth_headers) -> str:
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"BE-9605b {uuid4().hex[:8]}", "description": "template CRUD fixture"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_body(suffix: str, product_id: str, **overrides) -> dict:
    body = {
        "product_id": product_id,
        "role": "implementer",
        "custom_suffix": f"be9605b-{suffix}",
        "cli_tool": "claude",
        "description": "BE-9605b CRUD round trip",
        "user_instructions": "Body.",
        "is_active": False,
    }
    body.update(overrides)
    return body


async def test_create_defaults_model_and_effort_to_inherit(api_client, auth_headers, product_id) -> None:
    resp = await api_client.post(
        "/api/v1/templates/", json=_create_body(uuid4().hex[:6], product_id), headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["model"] == "inherit"
    assert data["effort"] == "inherit"


async def test_round_trip_stores_free_text_verbatim_after_strip(api_client, auth_headers, product_id) -> None:
    body = _create_body(
        uuid4().hex[:6], product_id, model="  claude-opus-5 or newer  ", effort="  think hard, take your time "
    )
    created = await api_client.post("/api/v1/templates/", json=body, headers=auth_headers)
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    assert created.json()["model"] == "claude-opus-5 or newer"
    assert created.json()["effort"] == "think hard, take your time"

    updated = await api_client.put(
        f"/api/v1/templates/{template_id}",
        json={"model": "whatever the newest is", "effort": "max"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["model"] == "whatever the newest is"
    assert updated.json()["effort"] == "max"

    fetched = await api_client.get(f"/api/v1/templates/{template_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["model"] == "whatever the newest is"
    assert fetched.json()["effort"] == "max"


@pytest.mark.parametrize("field", ["model", "effort"])
async def test_over_long_value_is_rejected_on_create_and_update(
    api_client, auth_headers, product_id, field: str
) -> None:
    too_long = "x" * 121
    created = await api_client.post(
        "/api/v1/templates/", json=_create_body(uuid4().hex[:6], product_id, **{field: too_long}), headers=auth_headers
    )
    assert created.status_code == 422, created.text
    assert field in created.text

    ok = await api_client.post(
        "/api/v1/templates/", json=_create_body(uuid4().hex[:6], product_id), headers=auth_headers
    )
    assert ok.status_code == 201, ok.text
    updated = await api_client.put(f"/api/v1/templates/{ok.json()['id']}", json={field: too_long}, headers=auth_headers)
    assert updated.status_code == 422, updated.text


@pytest.mark.parametrize("field", ["model", "effort"])
async def test_exactly_120_chars_is_accepted(api_client, auth_headers, product_id, field: str) -> None:
    value = "y" * 120
    created = await api_client.post(
        "/api/v1/templates/", json=_create_body(uuid4().hex[:6], product_id, **{field: value}), headers=auth_headers
    )
    assert created.status_code == 201, created.text
    assert created.json()[field] == value


async def test_blank_value_reads_back_as_inherit(api_client, auth_headers, product_id) -> None:
    created = await api_client.post(
        "/api/v1/templates/",
        json=_create_body(uuid4().hex[:6], product_id, model="   ", effort=""),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["model"] == "inherit"
    assert created.json()["effort"] == "inherit"
