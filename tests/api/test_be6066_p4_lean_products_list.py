# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

import pytest

from giljo_mcp.models.products import VisionDocument


def _extract_tenant_key(auth_headers: dict) -> str:
    import base64
    import json

    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


_RELATION_KEYS = ("tech_stack", "architecture", "test_config")


async def _seed_vision_docs(db_manager, tenant_key: str, product_id: str) -> None:
    async with db_manager.get_session_async() as session:
        session.add(
            VisionDocument(
                id=str(uuid4()),
                product_id=product_id,
                tenant_key=tenant_key,
                document_name="Doc A",
                document_type="vision",
                vision_document="x",
                storage_type="inline",
                chunked=True,
                chunk_count=3,
                summary_light="light",
                summary_medium="medium",
            )
        )
        session.add(
            VisionDocument(
                id=str(uuid4()),
                product_id=product_id,
                tenant_key=tenant_key,
                document_name="Doc B",
                document_type="vision",
                vision_document="x",
                storage_type="inline",
                chunked=True,
                chunk_count=2,
            )
        )
        session.add(
            VisionDocument(
                id=str(uuid4()),
                product_id=product_id,
                tenant_key=tenant_key,
                document_name="Doc C",
                document_type="vision",
                vision_document="x",
                storage_type="inline",
                summary_light="light",
                summary_medium="medium",
            )
        )
        session.add(
            VisionDocument(
                id=str(uuid4()),
                product_id=product_id,
                tenant_key=tenant_key,
                document_name="Doc D",
                document_type="vision",
                vision_document="x",
                storage_type="inline",
                summary_light="light",
                summary_medium="",
            )
        )
        await session.commit()


async def _create_product_with_detail(api_client, auth_headers) -> str:
    body = {
        "name": f"BE-6066 P4 {uuid4().hex[:8]}",
        "description": "lean-list fixture",
        "tech_stack": {"programming_languages": "Python", "backend_frameworks": "FastAPI"},
        "architecture": {"primary_pattern": "layered", "api_style": "REST"},
        "test_config": {"test_strategy": "pytest", "coverage_target": 90},
    }
    resp = await api_client.post("/api/v1/products/", headers=auth_headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
class TestLeanProductsList:

    async def test_list_omits_detail_relations_and_carries_vision_summary(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _create_product_with_detail(api_client, auth_headers)
        await _seed_vision_docs(db_manager, tenant_key, product_id)

        resp = await api_client.get("/api/v1/products/", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        products = resp.json()
        row = next(p for p in products if p["id"] == product_id)

        for key in (*_RELATION_KEYS, "vision_documents"):
            assert key not in row, f"lean list row must not carry {key!r}"

        assert "vision_summary" in row
        assert row["vision_summary"] == {
            "doc_count": 4,
            "chunked_count": 2,
            "chunk_total": 5,
            "embedded_count": 2,
        }
        assert row["vision_documents_count"] == 4
        assert row["has_vision"] is True

    async def test_get_by_id_still_returns_full_relations(self, api_client, auth_headers):
        product_id = await _create_product_with_detail(api_client, auth_headers)

        resp = await api_client.get(f"/api/v1/products/{product_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        for key in _RELATION_KEYS:
            assert key in body, f"detail response must carry {key!r}"
        assert body["tech_stack"]["programming_languages"] == "Python"
        assert body["architecture"]["primary_pattern"] == "layered"
        assert body["test_config"]["coverage_target"] == 90
