# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models.products import Product, VisionDocument
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_CSRF = secrets.token_urlsafe(32)


def _auth(token: str) -> dict:
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


@pytest_asyncio.fixture
async def lab(db_manager):
    from sqlalchemy import delete

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    product_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"VDoc Org {unique}", slug=f"vdoc-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"vdoc_{unique}",
                email=f"vdoc_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"unused", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
            )
        )
        session.add(
            Product(
                id=product_id,
                name=f"VDoc Product {unique}",
                tenant_key=tk,
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    token = JWTManager.create_access_token(
        user_id=user_id, username=f"vdoc_{unique}", role="developer", tenant_key=tk, revocation_epoch=0
    )

    yield {"tenant_key": tk, "product_id": product_id, "headers": _auth(token)}

    async with db_manager.get_session_async(tenant_key=tk) as session:
        await session.execute(delete(VisionDocument).where(VisionDocument.tenant_key == tk))
        await session.execute(delete(Product).where(Product.tenant_key == tk))
        await session.execute(delete(User).where(User.tenant_key == tk))
        await session.execute(delete(Organization).where(Organization.tenant_key == tk))
        await session.commit()


async def _add_doc(db_manager, lab, *, label: str, trashed: bool, tokens: int = 0, chunks: int = 0) -> str:
    doc_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=lab["tenant_key"]) as session:
        session.add(
            VisionDocument(
                id=doc_id,
                tenant_key=lab["tenant_key"],
                product_id=lab["product_id"],
                document_name=f"{label} doc",
                document_type="vision",
                vision_document=f"{label} body",
                storage_type="inline",
                is_active=True,
                deleted_at=datetime.now(UTC) if trashed else None,
                summary_light=f"{label} light summary",
                summary_medium=f"{label} medium summary",
                summary_light_tokens=11,
                summary_medium_tokens=22,
                chunked=chunks > 0,
                total_tokens=tokens,
                chunk_count=chunks,
            )
        )
        await session.commit()
    return doc_id




async def test_live_document_summary_is_still_served(api_client, db_manager, lab):
    doc_id = await _add_doc(db_manager, lab, label="live", trashed=False)

    response = await api_client.get(f"/api/vision-documents/{doc_id}/ai-summary/medium", headers=lab["headers"])

    assert response.status_code == 200, response.text
    assert response.json()["summary"] == "live medium summary"


async def test_trashed_document_summary_is_not_served(api_client, db_manager, lab):
    doc_id = await _add_doc(db_manager, lab, label="trashed", trashed=True)

    response = await api_client.get(f"/api/vision-documents/{doc_id}/ai-summary/medium", headers=lab["headers"])

    assert response.status_code == 404, (
        "a trashed vision document's AI summary is still being served -- the sibling "
        f"GET /{doc_id} in the same router returns 404 for it. body={response.text}"
    )


async def test_the_two_endpoints_agree_about_a_trashed_document(api_client, db_manager, lab):
    doc_id = await _add_doc(db_manager, lab, label="ghost", trashed=True)

    by_id = await api_client.get(f"/api/vision-documents/{doc_id}", headers=lab["headers"])
    summary = await api_client.get(f"/api/vision-documents/{doc_id}/ai-summary/light", headers=lab["headers"])

    assert by_id.status_code == 404
    assert summary.status_code == by_id.status_code, (
        f"the document endpoint says {by_id.status_code} but the summary endpoint says "
        f"{summary.status_code} for the same trashed document"
    )




async def _stats(api_client, lab) -> dict:
    response = await api_client.get("/api/v1/products/active/vision-stats", headers=lab["headers"])
    assert response.status_code == 200, response.text
    return response.json()


async def test_live_document_is_counted_in_vision_stats(api_client, db_manager, lab):
    await _add_doc(db_manager, lab, label="live", trashed=False, tokens=100, chunks=4)

    stats = await _stats(api_client, lab)

    assert stats["has_vision_document"] is True, f"a live document must be counted, got={stats}"
    assert stats["total_tokens"] == 100
    assert stats["chunk_count"] == 4


async def test_trashed_document_is_not_counted_in_vision_stats(api_client, db_manager, lab):
    await _add_doc(db_manager, lab, label="live", trashed=False, tokens=100, chunks=4)
    await _add_doc(db_manager, lab, label="trashed", trashed=True, tokens=999, chunks=77)

    stats = await _stats(api_client, lab)

    assert stats["total_tokens"] == 100, (
        f"a trashed vision document is still inflating the product's token total, got={stats}"
    )
    assert stats["chunk_count"] == 4, f"a trashed document is still inflating the chunk count, got={stats}"


async def test_stats_report_no_documents_when_the_only_one_is_trashed(api_client, db_manager, lab):
    await _add_doc(db_manager, lab, label="trashed", trashed=True, tokens=999, chunks=77)

    stats = await _stats(api_client, lab)

    assert stats["has_vision_document"] is False, (
        f"a product whose only vision document is trashed still reports having one, got={stats}"
    )
