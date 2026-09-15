# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from giljo_mcp.models.product_memory_entry import ProductMemoryEntry


def _extract_tenant_key(auth_headers: dict) -> str:
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _create_product(api_client, auth_headers) -> str:
    resp = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": f"BE-6082 {uuid4().hex[:8]}", "description": "fts fixture"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_entries(db_manager, tenant_key: str, product_id: str, specs: list[dict]) -> None:
    async with db_manager.get_session_async() as session:
        now = datetime.now(tz=UTC)
        for spec in specs:
            session.add(
                ProductMemoryEntry(
                    id=str(uuid4()),
                    tenant_key=tenant_key,
                    product_id=product_id,
                    sequence=spec["sequence"],
                    entry_type="project_completion",
                    source="test_v1",
                    timestamp=now,
                    summary=spec.get("summary"),
                    tags=spec.get("tags", []),
                )
            )
        await session.commit()


@pytest.mark.asyncio
class TestMemorySearchEndpoint:

    async def test_search_filters_entries(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _create_product(api_client, auth_headers)
        await _seed_entries(
            db_manager,
            tenant_key,
            product_id,
            [
                {"sequence": 1, "summary": "Refactored the tenant guard"},
                {"sequence": 2, "summary": "Upgraded the websocket broker"},
            ],
        )

        resp = await api_client.get(
            f"/api/v1/products/{product_id}/memory-entries", headers=auth_headers, params={"search": "tenant"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [e["sequence"] for e in body["entries"]] == [1]
        assert body["filtered_count"] == 1
        assert body["total_count"] == 2

    async def test_search_respects_limit(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _create_product(api_client, auth_headers)
        await _seed_entries(
            db_manager,
            tenant_key,
            product_id,
            [{"sequence": i + 1, "summary": f"shared keyword entry {i}"} for i in range(5)],
        )

        resp = await api_client.get(
            f"/api/v1/products/{product_id}/memory-entries",
            headers=auth_headers,
            params={"search": "keyword", "limit": 2},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["entries"]) == 2
        assert body["total_count"] == 5

    async def test_search_is_tenant_isolated(self, api_client, auth_headers, db_manager):
        product_id = await _create_product(api_client, auth_headers)
        await _seed_entries(
            db_manager,
            "tenant_intruder",
            product_id,
            [{"sequence": 1, "summary": "Secret roadmap for the intruder tenant"}],
        )

        resp = await api_client.get(
            f"/api/v1/products/{product_id}/memory-entries", headers=auth_headers, params={"search": "roadmap"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["entries"] == []

    async def test_overlong_search_term_is_422_not_500(self, api_client, auth_headers):
        product_id = await _create_product(api_client, auth_headers)
        resp = await api_client.get(
            f"/api/v1/products/{product_id}/memory-entries",
            headers=auth_headers,
            params={"search": "x" * 201},
        )
        assert resp.status_code == 422, resp.text
