# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.template_seeder import _get_default_templates_v103


pytestmark = pytest.mark.asyncio

IDENTITY_KEYS = ("id", "name", "role", "background_color", "cli_tool", "model", "effort", "product_id")


async def _make_product(api_client, auth_headers) -> str:
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"BE-9646 {uuid4().hex[:8]}", "description": "reset-all fixture"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _roster(api_client, auth_headers, product_id: str) -> dict[str, dict]:
    resp = await api_client.get("/api/v1/templates/", headers=auth_headers, params={"product_id": product_id})
    assert resp.status_code == 200, resp.text
    return {t["name"]: t for t in resp.json()}


async def _make_agent(api_client, auth_headers, product_id: str) -> dict:
    resp = await api_client.post(
        "/api/v1/templates/",
        headers=auth_headers,
        json={
            "product_id": product_id,
            "role": "tester",
            "custom_suffix": f"be9646-{uuid4().hex[:6]}",
            "cli_tool": "claude",
            "user_instructions": "Prose I wrote myself.",
            "is_active": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _shipped(role: str) -> str:
    return next(t for t in _get_default_templates_v103() if t["role"] == role)["user_instructions"]


async def test_reset_is_offered_on_origin_not_on_the_is_default_flag(api_client, auth_headers) -> None:
    product_id = await _make_product(api_client, auth_headers)
    mine = await _make_agent(api_client, auth_headers, product_id)

    crew = await _roster(api_client, auth_headers, product_id)
    assert crew, "creating a product seeds its factory crew"

    for agent in crew.values():
        if agent["name"] == mine["name"]:
            continue
        assert agent["can_reset"] is True, agent["name"]
        assert agent["is_default"] is False, agent["name"]

    assert mine["can_reset"] is False
    assert crew[mine["name"]]["can_reset"] is False


async def test_reset_all_restores_the_crew_and_leaves_everything_else_alone(api_client, auth_headers) -> None:
    product_id = await _make_product(api_client, auth_headers)
    mine = await _make_agent(api_client, auth_headers, product_id)
    before = await _roster(api_client, auth_headers, product_id)
    victim = next(a for a in before.values() if a["role"] == "tester" and a["name"] != mine["name"])

    switches = await api_client.get(f"/api/v1/products/{product_id}/agent-assignments", headers=auth_headers)
    assert switches.status_code == 200, switches.text
    switches_before = {a["template_id"]: a["is_active"] for a in switches.json()["assignments"]}

    edited = await api_client.put(
        f"/api/v1/templates/{victim['id']}",
        headers=auth_headers,
        json={"user_instructions": "Heavily customized."},
    )
    assert edited.status_code == 200, edited.text

    resp = await api_client.post("/api/v1/templates/reset-all", headers=auth_headers, params={"product_id": product_id})
    assert resp.status_code == 200, resp.text
    report = resp.json()

    assert report["failed"] == []
    assert mine["name"] in report["skipped"]
    assert victim["name"] in report["reset"]

    after = await _roster(api_client, auth_headers, product_id)
    assert after[victim["name"]]["user_instructions"] == _shipped("tester")
    assert after[mine["name"]]["user_instructions"] == "Prose I wrote myself."

    assert {n: {k: a[k] for k in IDENTITY_KEYS} for n, a in after.items()} == {
        n: {k: a[k] for k in IDENTITY_KEYS} for n, a in before.items()
    }
    for name in report["reset"]:
        assert "default" in after[name]["tags"], name
        assert after[name]["can_reset"] is True, name

    switches_after = await api_client.get(f"/api/v1/products/{product_id}/agent-assignments", headers=auth_headers)
    assert switches_after.status_code == 200, switches_after.text
    assert {a["template_id"]: a["is_active"] for a in switches_after.json()["assignments"]} == switches_before


async def test_reset_all_touches_only_the_product_named(api_client, auth_headers) -> None:
    product_id = await _make_product(api_client, auth_headers)
    other_id = await _make_product(api_client, auth_headers)
    other_before = await _roster(api_client, auth_headers, other_id)
    victim = next(iter(other_before.values()))

    edited = await api_client.put(
        f"/api/v1/templates/{victim['id']}",
        headers=auth_headers,
        json={"user_instructions": "Belongs to the other product."},
    )
    assert edited.status_code == 200, edited.text

    resp = await api_client.post("/api/v1/templates/reset-all", headers=auth_headers, params={"product_id": product_id})
    assert resp.status_code == 200, resp.text
    assert victim["name"] not in resp.json()["reset"]

    after = await _roster(api_client, auth_headers, other_id)
    assert after[victim["name"]]["user_instructions"] == "Belongs to the other product."
