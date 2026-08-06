# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Two more readers served trashed vision documents -- including one in the
router that was cited as the correct-behaviour precedent.

**The AI-summary contradiction.** ``GET /api/vision-documents/{id}`` filters
``deleted_at IS NULL`` and carries an explicit ``BE-6130b: trashed docs are not
retrievable here`` comment. Its neighbour in the same file,
``GET /api/vision-documents/{id}/ai-summary/{level}``, selects on ``id`` +
``tenant_key`` only. For one trashed document, the two endpoints disagree:

    GET /api/vision-documents/{id}                    -> 404 "not found"
    GET /api/vision-documents/{id}/ai-summary/medium  -> 200 + the summary text

One says the document is gone; the other hands over its content. This is the
sharpest instance in the family, and it sat in the file used as the standard --
which is exactly how the earlier instances survived: the correct predicate was
present NEARBY, so the file read as clean.

**The vision-stats count.** ``GET /api/v1/products/active/vision-stats`` filters
``is_active == True`` with no ``deleted_at`` -- the same shape already fixed on
the product-scoped list endpoint, so trashed documents kept inflating the
document count and token totals.

Each pair is a defect scenario plus its over-exclusion guard: a LIVE document's
summary must still be served, and a LIVE document must still be counted. A fix
that returns 404 for everything, or counts nothing, would pass the defect half
while destroying the endpoint.

Real rows, committed through ``db_manager`` -- these endpoints resolve their own
sessions, and a mock cannot see a predicate.
"""

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
    """Committed ACTIVE product + user; torn down afterwards.

    The product must be active because ``/active/vision-stats`` resolves its
    product through ``ProductService.get_active_product()``.
    """
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
                # ck_vision_doc_chunked_consistency: a non-zero chunk_count
                # requires chunked=True, so honour the DB invariant rather than
                # constructing a row that could not exist in production.
                chunked=chunks > 0,
                total_tokens=tokens,
                chunk_count=chunks,
            )
        )
        await session.commit()
    return doc_id


# --- GET /api/vision-documents/{id}/ai-summary/{level} ----------------------


async def test_live_document_summary_is_still_served(api_client, db_manager, lab):
    """THE OVER-EXCLUSION GUARD. A fix that 404s everything would pass the
    trashed case while breaking the feature."""
    doc_id = await _add_doc(db_manager, lab, label="live", trashed=False)

    response = await api_client.get(f"/api/vision-documents/{doc_id}/ai-summary/medium", headers=lab["headers"])

    assert response.status_code == 200, response.text
    assert response.json()["summary"] == "live medium summary"


async def test_trashed_document_summary_is_not_served(api_client, db_manager, lab):
    """THE DEFECT. The sibling GET in the same file already 404s this document."""
    doc_id = await _add_doc(db_manager, lab, label="trashed", trashed=True)

    response = await api_client.get(f"/api/vision-documents/{doc_id}/ai-summary/medium", headers=lab["headers"])

    assert response.status_code == 404, (
        "a trashed vision document's AI summary is still being served -- the sibling "
        f"GET /{doc_id} in the same router returns 404 for it. body={response.text}"
    )


async def test_the_two_endpoints_agree_about_a_trashed_document(api_client, db_manager, lab):
    """The contradiction itself, asserted directly: one document must not be
    simultaneously absent and readable."""
    doc_id = await _add_doc(db_manager, lab, label="ghost", trashed=True)

    by_id = await api_client.get(f"/api/vision-documents/{doc_id}", headers=lab["headers"])
    summary = await api_client.get(f"/api/vision-documents/{doc_id}/ai-summary/light", headers=lab["headers"])

    assert by_id.status_code == 404
    assert summary.status_code == by_id.status_code, (
        f"the document endpoint says {by_id.status_code} but the summary endpoint says "
        f"{summary.status_code} for the same trashed document"
    )


# --- GET /api/v1/products/active/vision-stats ------------------------------


async def _stats(api_client, lab) -> dict:
    response = await api_client.get("/api/v1/products/active/vision-stats", headers=lab["headers"])
    assert response.status_code == 200, response.text
    return response.json()


async def test_live_document_is_counted_in_vision_stats(api_client, db_manager, lab):
    """THE OVER-EXCLUSION GUARD for the stats count."""
    await _add_doc(db_manager, lab, label="live", trashed=False, tokens=100, chunks=4)

    stats = await _stats(api_client, lab)

    assert stats["has_vision_document"] is True, f"a live document must be counted, got={stats}"
    assert stats["total_tokens"] == 100
    assert stats["chunk_count"] == 4


async def test_trashed_document_is_not_counted_in_vision_stats(api_client, db_manager, lab):
    """THE DEFECT. is_active is filtered but deleted_at is not -- soft-delete
    deliberately leaves is_active alone, so trashed docs kept inflating totals."""
    await _add_doc(db_manager, lab, label="live", trashed=False, tokens=100, chunks=4)
    await _add_doc(db_manager, lab, label="trashed", trashed=True, tokens=999, chunks=77)

    stats = await _stats(api_client, lab)

    assert stats["total_tokens"] == 100, (
        f"a trashed vision document is still inflating the product's token total, got={stats}"
    )
    assert stats["chunk_count"] == 4, f"a trashed document is still inflating the chunk count, got={stats}"


async def test_stats_report_no_documents_when_the_only_one_is_trashed(api_client, db_manager, lab):
    """has_vision_document must follow the same rule, not just the sums."""
    await _add_doc(db_manager, lab, label="trashed", trashed=True, tokens=999, chunks=77)

    stats = await _stats(api_client, lab)

    assert stats["has_vision_document"] is False, (
        f"a product whose only vision document is trashed still reports having one, got={stats}"
    )
