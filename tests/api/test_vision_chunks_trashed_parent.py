# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Trashing a vision document did not stop its text being served.

``GET /api/v1/products/{id}/vision-chunks`` selected ``MCPContextIndex`` on
junction columns only -- ``tenant_key``, ``product_id`` and
``vision_document_id IS NOT NULL`` -- and never revalidated the
``VisionDocument`` each chunk points at. Soft-delete does **not** cascade (it
stamps ``deleted_at`` and deliberately leaves the chunks intact so a restore
brings the document and its chunks back as one unit), so every chunk of a
trashed document survived and this endpoint kept returning its full text.

This is not merely surprising behaviour: ``vision_document_repository.soft_delete``
states the contract in its own docstring -- *"chunk retrieval excludes chunks of
a trashed parent"*. The sibling reader ``context_repository.search_chunks``
honours it with a ``NOT EXISTS`` on ``vision_documents.deleted_at``. This
endpoint was the one reader that did not.

The three scenarios are the whole contract:

* **live** -- a live document's chunks are still served (the over-exclusion guard)
* **trashed** -- a trashed document's chunks are gone
* **mixed** -- with one live and one trashed document, exactly the live one's
  chunks come back, proving the filter is per-document rather than all-or-nothing

**The live scenario is the guard against over-correcting.** A fix that drops
chunks whose parent is fine -- or that returns nothing whenever any document is
trashed -- makes the trashed case pass while destroying the endpoint. It is
mutation-proved in the same way scenario B was for the agent-template fix.

Rows are committed through ``db_manager`` rather than the rollback-isolated
``db_session``, because the endpoint resolves its own session and cannot see an
uncommitted transaction. Each test cleans up exactly the rows it created. This
is a predicate defect and a mock cannot see a predicate.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from uuid import uuid4

import bcrypt
import pytest
import pytest_asyncio

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models.context import MCPContextIndex
from giljo_mcp.models.products import Product, VisionDocument
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_CSRF = secrets.token_urlsafe(32)


def _auth(token: str) -> dict:
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


@pytest_asyncio.fixture
async def lab(db_manager):
    """Committed product + user for one test; torn down afterwards."""
    from sqlalchemy import delete

    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    product_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(name=f"Chunks Org {unique}", slug=f"chunks-org-{unique}", tenant_key=tk, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"chunks_{unique}",
                email=f"chunks_{unique}@example.com",
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
                name=f"Chunks Product {unique}",
                tenant_key=tk,
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    token = JWTManager.create_access_token(
        user_id=user_id, username=f"chunks_{unique}", role="developer", tenant_key=tk, revocation_epoch=0
    )

    yield {"tenant_key": tk, "product_id": product_id, "headers": _auth(token)}

    async with db_manager.get_session_async(tenant_key=tk) as session:
        await session.execute(delete(MCPContextIndex).where(MCPContextIndex.tenant_key == tk))
        await session.execute(delete(VisionDocument).where(VisionDocument.tenant_key == tk))
        await session.execute(delete(Product).where(Product.tenant_key == tk))
        await session.execute(delete(User).where(User.tenant_key == tk))
        await session.execute(delete(Organization).where(Organization.tenant_key == tk))
        await session.commit()


async def _add_doc_with_chunks(db_manager, lab, *, label: str, trashed: bool) -> str:
    """Commit one vision document plus two chunks; return the document id."""
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
            )
        )
        for order in (0, 1):
            session.add(
                MCPContextIndex(
                    tenant_key=lab["tenant_key"],
                    product_id=lab["product_id"],
                    vision_document_id=doc_id,
                    content=f"{label} chunk {order}",
                    keywords=[label],
                    chunk_order=order,
                )
            )
        await session.commit()
    return doc_id


async def _get_chunk_contents(api_client, lab) -> list[str]:
    response = await api_client.get(f"/api/v1/products/{lab['product_id']}/vision-chunks", headers=lab["headers"])
    assert response.status_code == 200, response.text
    return [chunk["content"] for chunk in response.json()]


async def test_live_document_chunks_are_still_served(api_client, db_manager, lab):
    """THE OVER-EXCLUSION GUARD. A fix that hides chunks of a healthy document
    makes the trashed case pass while destroying the endpoint."""
    await _add_doc_with_chunks(db_manager, lab, label="live", trashed=False)

    contents = await _get_chunk_contents(api_client, lab)

    assert sorted(contents) == ["live chunk 0", "live chunk 1"], (
        f"a live document's chunks must still be served, got={contents}"
    )


async def test_trashed_document_chunks_are_not_served(api_client, db_manager, lab):
    """THE DEFECT. Soft-delete does not cascade, so the chunks survive -- they
    must simply stop being retrieved until the document is restored."""
    await _add_doc_with_chunks(db_manager, lab, label="trashed", trashed=True)

    contents = await _get_chunk_contents(api_client, lab)

    assert contents == [], (
        "a trashed vision document's text is still being served -- "
        f"vision_document_repository.soft_delete promises the opposite. got={contents}"
    )


async def test_only_the_live_documents_chunks_come_back(api_client, db_manager, lab):
    """The filter must be per-document, not all-or-nothing in either direction."""
    await _add_doc_with_chunks(db_manager, lab, label="keep", trashed=False)
    await _add_doc_with_chunks(db_manager, lab, label="gone", trashed=True)

    contents = await _get_chunk_contents(api_client, lab)

    assert sorted(contents) == ["keep chunk 0", "keep chunk 1"], (
        f"expected only the live document's chunks, got={contents}"
    )


# ---------------------------------------------------------------------------
# The sibling reader in the same router: GET /{product_id}/vision.
#
# Absorbed deliberately rather than deferred. BE-9334 fixed two instances of
# this class in one file and left the third, and that is exactly why nobody
# found it for weeks: the predicate was present NEARBY, so the file read as
# clean. Shipping the chunks fix while a sibling defect sits two hundred lines
# away in the same file would hand the next reader the same false signal.
# ---------------------------------------------------------------------------


async def _get_listed_document_names(api_client, lab) -> list[str]:
    response = await api_client.get(f"/api/v1/products/{lab['product_id']}/vision", headers=lab["headers"])
    assert response.status_code == 200, response.text
    return [doc["document_name"] for doc in response.json()]


async def test_live_document_is_still_listed(api_client, db_manager, lab):
    """THE OVER-EXCLUSION GUARD for the list endpoint. A fix that hides healthy
    documents makes the trashed case pass while emptying the user's library."""
    await _add_doc_with_chunks(db_manager, lab, label="live", trashed=False)

    names = await _get_listed_document_names(api_client, lab)

    assert names == ["live doc"], f"a live vision document must still be listed, got={names}"


async def test_trashed_document_is_not_listed(api_client, db_manager, lab):
    """THE DEFECT. The sibling router api/endpoints/vision_documents.py filters
    deleted_at and offers a dedicated /deleted trash view, so a trashed document
    reappearing in the main list here contradicts the product's own model of
    what "trash" means."""
    await _add_doc_with_chunks(db_manager, lab, label="trashed", trashed=True)

    names = await _get_listed_document_names(api_client, lab)

    assert names == [], f"a trashed vision document is still listed as live, got={names}"


async def test_only_the_live_document_is_listed(api_client, db_manager, lab):
    """Per-document, not all-or-nothing in either direction."""
    await _add_doc_with_chunks(db_manager, lab, label="keep", trashed=False)
    await _add_doc_with_chunks(db_manager, lab, label="gone", trashed=True)

    names = await _get_listed_document_names(api_client, lab)

    assert names == ["keep doc"], f"expected only the live document, got={names}"
