# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.services.vision_hash import compute_vision_inputs_hash
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.vision_analysis import create_vision_document


@pytest_asyncio.fixture(scope="function")
async def tenant_a() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture(scope="function")
async def product_a(db_session: AsyncSession, tenant_a: str) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name=f"Bootstrap Product {uuid.uuid4().hex[:8]}",
        description="Product for BE-9201 bootstrap testing",
        tenant_key=tenant_a,
        is_active=False,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return product


CONTENT = "# Vision\n\nAgent-authored vision body.\n\n## Scope\n\nOnboarding tutorial paths B and D."




@pytest.mark.asyncio
async def test_empty_content_rejected(db_session, tenant_a, product_a):
    with pytest.raises(ValidationError, match="content is required"):
        await create_vision_document(
            product_id=product_a.id,
            tenant_key=tenant_a,
            content="   \n  ",
            _test_session=db_session,
        )


@pytest.mark.asyncio
async def test_oversize_content_rejected_at_the_rest_cap(db_session, tenant_a, product_a, monkeypatch):
    from giljo_mcp.tools import vision_analysis as va

    real_config = va.get_config()
    monkeypatch.setattr(real_config.upload, "max_upload_bytes", 64)

    with pytest.raises(ValidationError, match="maximum vision document size"):
        await create_vision_document(
            product_id=product_a.id,
            tenant_key=tenant_a,
            content="x" * 65,
            _test_session=db_session,
        )


@pytest.mark.asyncio
async def test_bad_document_name_rejected(db_session, tenant_a, product_a):
    with pytest.raises(ValidationError, match="Invalid document_name"):
        await create_vision_document(
            product_id=product_a.id,
            tenant_key=tenant_a,
            content=CONTENT,
            document_name="../../etc/passwd.md",
            _test_session=db_session,
        )


@pytest.mark.asyncio
async def test_unknown_product_not_found(db_session, tenant_a):
    with pytest.raises(ResourceNotFoundError):
        await create_vision_document(
            product_id=str(uuid.uuid4()),
            tenant_key=tenant_a,
            content=CONTENT,
            _test_session=db_session,
        )


@pytest.mark.asyncio
async def test_duplicate_document_name_rejected(db_session, tenant_a, product_a):
    first = await create_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        content=CONTENT,
        document_name="Product Vision.md",
        _test_session=db_session,
    )
    assert first["success"] is True

    with pytest.raises(ValidationError):
        await create_vision_document(
            product_id=product_a.id,
            tenant_key=tenant_a,
            content="# Vision\n\nDifferent body, same name.",
            document_name="Product Vision.md",
            _test_session=db_session,
        )




@pytest.mark.asyncio
async def test_feeds_the_same_staleness_machinery_as_the_ui_upload(db_session, tenant_a, product_a):
    result = await create_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        content=CONTENT,
        _test_session=db_session,
    )
    assert result["success"] is True

    product = (
        await db_session.execute(select(Product).where(Product.id == product_a.id, Product.tenant_key == tenant_a))
    ).scalar_one()
    docs = (
        (
            await db_session.execute(
                select(VisionDocument).where(
                    VisionDocument.product_id == product_a.id, VisionDocument.tenant_key == tenant_a
                )
            )
        )
        .scalars()
        .all()
    )

    derived = compute_vision_inputs_hash(docs)
    assert product.consolidated_vision_hash, "auto-consolidation must persist the aggregate hash"
    assert derived == f"sha256:{product.consolidated_vision_hash}", (
        "agent-written doc must land in the same consolidation/staleness pipeline as a UI upload"
    )
    assert product.vision_analysis_complete is False


@pytest.mark.asyncio
async def test_default_name_and_extension_append(db_session, tenant_a, product_a):
    omitted = await create_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        content=CONTENT,
        _test_session=db_session,
    )
    assert omitted["document_name"] == "Agent Vision.md"

    extensionless = await create_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        content="# Vision\n\nSecond doc body.",
        document_name="roadmap",
        _test_session=db_session,
    )
    assert extensionless["document_name"] == "roadmap.md"




@pytest.mark.asyncio
async def test_create_product_adapter_rejects_whitespace_name(db_manager, db_session, tenant_a):
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    with pytest.raises(ValidationError, match="name is required"):
        await accessor.create_product(name="   ", tenant_key=tenant_a)


@pytest.mark.asyncio
async def test_create_product_adapter_strips_name_and_defaults(db_manager, db_session, tenant_a):
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    name = f"Padded Name {uuid.uuid4().hex[:8]}"
    result = await accessor.create_product(name=f"  {name}  ", tenant_key=tenant_a)
    assert result["success"] is True
    assert result["name"] == name
    assert result["is_active"] is True
    assert result["target_platforms"] == ["all"]
