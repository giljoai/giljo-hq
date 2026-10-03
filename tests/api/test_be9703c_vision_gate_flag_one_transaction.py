# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.services.product_vision_service import ProductVisionService


def _tenant_key_of(auth_headers: dict) -> str:
    token = auth_headers["Cookie"].split("access_token=")[1].split(";")[0]
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["tenant_key"]


async def _product(db_manager, tenant_key: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid4()),
            tenant_key=tenant_key,
            name=f"A07 {uuid4().hex[:6]}",
            description="d",
            vision_analysis_complete=True,
        )
        session.add(product)
        await session.commit()
        return str(product.id)


async def _flag(db_manager, tenant_key: str, product_id: str) -> bool:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return (
            await session.execute(select(Product.vision_analysis_complete).where(Product.id == product_id))
        ).scalar_one()


@pytest.mark.asyncio
async def test_the_upload_service_recomputes_the_gate_flag(db_manager):
    tenant_key = f"tk_a07_{uuid4().hex[:8]}"
    product_id = await _product(db_manager, tenant_key)
    service = ProductVisionService(db_manager=db_manager, tenant_key=tenant_key)
    await service.upload_vision_document(
        product_id=product_id, content="# Vision\nbody\n", filename="v.md", auto_chunk=False
    )
    assert await _flag(db_manager, tenant_key, product_id) is False, (
        "a new unsummarized document must drop the gate flag"
    )


@pytest.mark.asyncio
async def test_a_failed_recompute_does_not_leave_a_committed_delete(api_client, auth_headers, db_manager, monkeypatch):
    tenant_key = _tenant_key_of(auth_headers)
    product_id = await _product(db_manager, tenant_key)
    upload = await api_client.post(
        f"/api/v1/products/{product_id}/vision",
        headers=auth_headers,
        files={"file": ("v.md", b"# Vision\nbody\n", "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["document_id"]

    async def _boom(self, session, pid):
        raise RuntimeError("recompute failed")

    monkeypatch.setattr(ProductVisionService, "evaluate_vision_analysis_complete", _boom)
    try:
        response = await api_client.delete(f"/api/v1/products/{product_id}/vision/{doc_id}", headers=auth_headers)
    except RuntimeError:
        response = None
    assert response is None or response.status_code >= 500, response.text
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        still_there = (
            await session.execute(select(VisionDocument.id).where(VisionDocument.id == doc_id))
        ).scalar_one_or_none()
    assert still_there == doc_id, "the delete and the flag recompute are one transaction"
