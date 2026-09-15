# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.models.products import (
    ProductArchitecture,
    ProductTechStack,
    ProductTestConfig,
)
from giljo_mcp.repositories.vision_document_repository import VisionDocumentRepository
from giljo_mcp.tenant import TenantManager




@pytest_asyncio.fixture(scope="function")
async def vision_repo(db_manager) -> VisionDocumentRepository:
    return VisionDocumentRepository(db_manager)


@pytest_asyncio.fixture(scope="function")
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture(scope="function")
async def product(db_session: AsyncSession, tenant_key: str) -> Product:
    p = Product(
        id=str(uuid.uuid4()),
        name="E2E Test Product",
        description="Product for E2E vision analysis testing",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
        extraction_custom_instructions="Focus on mobile architecture",
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest_asyncio.fixture(scope="function")
async def vision_doc(db_session: AsyncSession, tenant_key: str, product: Product) -> VisionDocument:
    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        document_name="Product Vision",
        document_type="vision",
        vision_document=(
            "This product is a mobile-first platform for real-time collaboration. "
            "It uses React Native for the frontend and FastAPI for the backend. "
            "The architecture follows event-driven microservices with PostgreSQL "
            "as the primary datastore. Testing strategy is TDD with pytest and Jest. "
            "Target coverage is 90 percent."
        ),
        storage_type="inline",
        content_hash="e2e_hash_001",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc




@pytest.mark.asyncio
async def test_e2e_full_analysis_flow(
    db_session: AsyncSession,
    db_manager,
    tenant_key: str,
    product: Product,
    vision_doc: VisionDocument,
):
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document
    from giljo_mcp.tools.vision_analysis import update_product_fields

    get_result = await get_vision_document(
        product_id=product.id,
        tenant_key=tenant_key,
        _test_session=db_session,
    )

    assert get_result["product_id"] == product.id
    assert get_result["product_name"] == "E2E Test Product"
    assert get_result["total_chunks"] >= 1
    assert get_result["write_tool"] == "update_product_context"
    assert get_result["doc_ids"] == [str(vision_doc.id)]
    assert "extraction_instructions" in get_result

    chunk1 = await get_vision_document(
        product_id=product.id,
        tenant_key=tenant_key,
        chunk=1,
        _test_session=db_session,
    )
    assert "mobile-first platform" in chunk1["content"]
    assert chunk1["doc_id"] == str(vision_doc.id)

    mock_ws = AsyncMock()

    write_result = await update_product_fields(
        product_id=product.id,
        tenant_key=tenant_key,
        _test_session=db_session,
        websocket_manager=mock_ws,
        product_description="A mobile-first real-time collaboration platform.",
        core_features="Real-time collaboration, mobile support",
        target_platforms=["windows", "linux", "macos"],
        programming_languages="Python, TypeScript",
        frontend_frameworks="React Native",
        databases="PostgreSQL",
        architecture_pattern="Event-driven microservices",
        api_style="REST",
        testing_strategy="TDD",
        testing_frameworks="pytest, Jest",
        test_coverage_target=90,
        vision_summaries=[
            {
                "doc_id": str(vision_doc.id),
                "light": "Mobile-first collaboration platform using React Native and FastAPI.",
                "medium": (
                    "Mobile-first real-time collaboration platform built on React "
                    "Native and FastAPI with event-driven microservices over PostgreSQL."
                ),
            }
        ],
        consolidated_vision={
            "light": "Mobile-first collaboration platform.",
            "medium": (
                "Mobile-first real-time collaboration platform. React Native + FastAPI. "
                "Event-driven microservices on PostgreSQL. TDD with pytest and Jest."
            ),
        },
    )

    assert write_result["success"] is True
    expected_fields = {
        "product_description",
        "core_features",
        "target_platforms",
        "programming_languages",
        "frontend_frameworks",
        "databases",
        "architecture_pattern",
        "api_style",
        "testing_strategy",
        "testing_frameworks",
        "test_coverage_target",
        "vision_summaries",
        "consolidated_vision",
    }
    assert set(write_result["fields"]) == expected_fields

    await db_session.refresh(product)
    assert product.description == "A mobile-first real-time collaboration platform."
    assert product.core_features == "Real-time collaboration, mobile support"
    assert product.target_platforms == ["windows", "linux", "macos"]
    assert product.consolidated_vision_light.startswith("Mobile-first collaboration platform.")
    assert "Event-driven microservices" in product.consolidated_vision_medium
    assert product.vision_analysis_complete is True

    await db_session.refresh(vision_doc)
    assert vision_doc.summary_light.startswith("Mobile-first collaboration platform")
    assert "React Native and FastAPI" in vision_doc.summary_medium
    assert vision_doc.is_summarized is True

    ts = (
        await db_session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts is not None
    assert ts.programming_languages == "Python, TypeScript"
    assert ts.frontend_frameworks == "React Native"
    assert ts.databases_storage == "PostgreSQL"

    arch = (
        await db_session.execute(
            select(ProductArchitecture).where(
                ProductArchitecture.product_id == product.id,
                ProductArchitecture.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert arch is not None
    assert arch.primary_pattern == "Event-driven microservices"
    assert arch.api_style == "REST"

    tc = (
        await db_session.execute(
            select(ProductTestConfig).where(
                ProductTestConfig.product_id == product.id,
                ProductTestConfig.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert tc is not None
    assert tc.test_strategy == "TDD"
    assert tc.testing_frameworks == "pytest, Jest"
    assert tc.coverage_target == 90

    mock_ws.broadcast_event_to_tenant.assert_called_once()
    event = mock_ws.broadcast_event_to_tenant.call_args[1]["event"]
    assert event["type"] == "vision:analysis_complete"
    assert event["data"]["product_id"] == product.id




@pytest.mark.asyncio
async def test_e2e_partial_field_write_no_overwrite(
    db_session: AsyncSession,
    db_manager,
    tenant_key: str,
    product: Product,
    vision_doc: VisionDocument,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result1 = await update_product_fields(
        product_id=product.id,
        tenant_key=tenant_key,
        _test_session=db_session,
        product_description="Initial description from first analysis pass.",
        programming_languages="Python, TypeScript",
    )

    assert result1["success"] is True
    assert set(result1["fields"]) == {"product_description", "programming_languages"}

    await db_session.refresh(product)
    assert product.description == "Initial description from first analysis pass."

    ts = (
        await db_session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts is not None
    assert ts.programming_languages == "Python, TypeScript"

    result2 = await update_product_fields(
        product_id=product.id,
        tenant_key=tenant_key,
        _test_session=db_session,
        architecture_pattern="Monolith",
        testing_strategy="BDD",
    )

    assert result2["success"] is True
    assert set(result2["fields"]) == {"architecture_pattern", "testing_strategy"}

    await db_session.refresh(product)
    assert product.description == "Initial description from first analysis pass."

    ts = (
        await db_session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts is not None
    assert ts.programming_languages == "Python, TypeScript"

    arch = (
        await db_session.execute(
            select(ProductArchitecture).where(
                ProductArchitecture.product_id == product.id,
                ProductArchitecture.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert arch is not None
    assert arch.primary_pattern == "Monolith"

    tc = (
        await db_session.execute(
            select(ProductTestConfig).where(
                ProductTestConfig.product_id == product.id,
                ProductTestConfig.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert tc is not None
    assert tc.test_strategy == "BDD"




@pytest.mark.asyncio
async def test_e2e_custom_instructions(
    db_session: AsyncSession,
    db_manager,
    tenant_key: str,
    product: Product,
    vision_doc: VisionDocument,
):
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    result_with = await get_vision_document(
        product_id=product.id,
        tenant_key=tenant_key,
        _test_session=db_session,
    )

    assert "Focus on mobile architecture" in result_with["extraction_instructions"]

    product.extraction_custom_instructions = None
    await db_session.flush()

    result_without = await get_vision_document(
        product_id=product.id,
        tenant_key=tenant_key,
        _test_session=db_session,
    )

    assert "Focus on mobile architecture" not in result_without["extraction_instructions"]
    assert "{custom_instructions}" not in result_without["extraction_instructions"]

    chunk_with = await get_vision_document(
        product_id=product.id,
        tenant_key=tenant_key,
        chunk=1,
        _test_session=db_session,
    )
    chunk_without = await get_vision_document(
        product_id=product.id,
        tenant_key=tenant_key,
        chunk=1,
        _test_session=db_session,
    )
    assert "mobile-first platform" in chunk_with["content"]
    assert "mobile-first platform" in chunk_without["content"]
