# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for vision analysis MCP tools: get_vision_document and update_product_context.

Handover 0842c: TDD tests written FIRST before implementation.
Covers happy paths, tenant isolation, partial writes, and WebSocket emission.
"""

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
    """Create VisionDocumentRepository instance for testing."""
    return VisionDocumentRepository(db_manager)


@pytest_asyncio.fixture(scope="function")
async def tenant_a() -> str:
    """Generate tenant key A."""
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture(scope="function")
async def tenant_b() -> str:
    """Generate tenant key B (for cross-tenant isolation tests)."""
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture(scope="function")
async def product_a(db_session: AsyncSession, tenant_a: str) -> Product:
    """Create test product for tenant A with extraction_custom_instructions."""
    product = Product(
        id=str(uuid.uuid4()),
        name="Test Product A",
        description="Product for vision analysis testing",
        tenant_key=tenant_a,
        is_active=True,
        product_memory={},
        extraction_custom_instructions="Focus on backend architecture.",
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest_asyncio.fixture(scope="function")
async def product_a_no_instructions(db_session: AsyncSession, tenant_a: str) -> Product:
    """Create test product for tenant A without custom extraction instructions."""
    product = Product(
        id=str(uuid.uuid4()),
        name="Test Product No Instructions",
        description="Product without custom extraction instructions",
        tenant_key=tenant_a,
        is_active=False,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest_asyncio.fixture(scope="function")
async def product_b(db_session: AsyncSession, tenant_b: str) -> Product:
    """Create test product for tenant B (cross-tenant isolation)."""
    product = Product(
        id=str(uuid.uuid4()),
        name="Test Product B",
        description="Product for cross-tenant testing",
        tenant_key=tenant_b,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest_asyncio.fixture(scope="function")
async def doc_a(db_session: AsyncSession, tenant_a: str, product_a: Product) -> VisionDocument:
    """Create active vision document for product A."""
    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=tenant_a,
        product_id=product_a.id,
        document_name="Product Vision",
        document_type="vision",
        vision_document="This is the main vision document content for testing.",
        storage_type="inline",
        content_hash="abc123",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


@pytest_asyncio.fixture(scope="function")
async def doc_a2(db_session: AsyncSession, tenant_a: str, product_a: Product) -> VisionDocument:
    """Create second active vision document for product A."""
    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=tenant_a,
        product_id=product_a.id,
        document_name="Architecture Doc",
        document_type="architecture",
        vision_document="Architecture details for the product.",
        storage_type="inline",
        content_hash="def456",
        is_active=True,
        display_order=1,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


@pytest_asyncio.fixture(scope="function")
async def doc_b(db_session: AsyncSession, tenant_b: str, product_b: Product) -> VisionDocument:
    """Create vision document for tenant B product."""
    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=tenant_b,
        product_id=product_b.id,
        document_name="Tenant B Vision",
        document_type="vision",
        vision_document="This is tenant B content.",
        storage_type="inline",
        content_hash="ghi789",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


# ---------------------------------------------------------------------------
# Tests for get_vision_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vision_doc_happy_path(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
    doc_a: VisionDocument,
):
    """Product with vision doc returns content, prompt, and metadata."""
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    result = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
    )

    assert result["product_id"] == product_a.id
    assert result["product_name"] == "Test Product A"
    assert result["total_chunks"] >= 1
    assert result["total_tokens"] > 0
    assert result["write_tool"] == "update_product_context"
    assert "extraction_instructions" in result
    assert "{custom_instructions}" not in result["extraction_instructions"]
    # Metadata-only call should include usage hint, not content
    assert "usage" in result

    # Request chunk 1 to get actual content
    chunk_result = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        chunk=1,
        _test_session=db_session,
    )
    assert "vision document content" in chunk_result["content"]
    assert chunk_result["chunk"] == 1


@pytest.mark.asyncio
async def test_get_vision_doc_not_found(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
):
    """Nonexistent product raises ResourceNotFoundError."""
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.exceptions import ResourceNotFoundError
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    # Scope the bare test session to tenant_a (mirrors the sibling
    # test_get_vision_doc_tenant_isolation) so the tool's explicit tenant
    # predicate is authorized and a missing product yields ResourceNotFoundError
    # rather than a guard TenantIsolationError.
    with pytest.raises(ResourceNotFoundError):
        with tenant_session_context(db_session, tenant_a):
            await get_vision_document(
                product_id=str(uuid.uuid4()),
                tenant_key=tenant_a,
                _test_session=db_session,
            )


@pytest.mark.asyncio
async def test_get_vision_doc_tenant_isolation(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    tenant_b: str,
    product_b: Product,
    doc_b: VisionDocument,
):
    """Cannot read another tenant's product vision documents."""
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.exceptions import ResourceNotFoundError
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    with pytest.raises(ResourceNotFoundError):
        with tenant_session_context(db_session, tenant_a):
            await get_vision_document(
                product_id=product_b.id,
                tenant_key=tenant_a,
                _test_session=db_session,
            )


@pytest.mark.asyncio
async def test_get_vision_doc_custom_instructions(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
    doc_a: VisionDocument,
):
    """Custom extraction instructions are injected into the prompt."""
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    result = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
    )

    assert "Focus on backend architecture." in result["extraction_instructions"]


@pytest.mark.asyncio
async def test_get_vision_doc_no_vision_docs(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a_no_instructions: Product,
):
    """Product without vision documents raises ResourceNotFoundError."""
    from giljo_mcp.exceptions import ResourceNotFoundError
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    with pytest.raises(ResourceNotFoundError, match="No vision documents found"):
        await get_vision_document(
            product_id=product_a_no_instructions.id,
            tenant_key=tenant_a,
            _test_session=db_session,
        )


# ---------------------------------------------------------------------------
# Tests for update_product_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_product_core_fields(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """Writes product_name, description, and core_features to product."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    # force=True: product_a already has a name, and product_name is user-owned
    # (BE-9164) — force is required to overwrite it in this core-fields write.
    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        force=True,
        product_name="Updated Product Name",
        product_description="A new description.",
        core_features="Feature A, Feature B",
        brand_guidelines="Dark navy theme, #ffd700 brand yellow, WCAG AA contrast",
    )

    assert result["success"] is True
    assert result["fields_written"] == 4
    assert "product_name" in result["fields"]
    assert "product_description" in result["fields"]
    assert "core_features" in result["fields"]
    assert "brand_guidelines" in result["fields"]

    # Verify values persisted
    await db_session.refresh(product_a)
    assert product_a.name == "Updated Product Name"
    assert product_a.description == "A new description."
    assert product_a.core_features == "Feature A, Feature B"
    assert product_a.brand_guidelines == "Dark navy theme, #ffd700 brand yellow, WCAG AA contrast"


@pytest.mark.asyncio
async def test_write_product_tech_stack(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """Writes tech stack fields to product_tech_stacks table."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        programming_languages="Python, TypeScript",
        databases="PostgreSQL, Redis",
        infrastructure="Docker, Kubernetes",
    )

    assert result["success"] is True
    assert "programming_languages" in result["fields"]
    assert "databases" in result["fields"]
    assert "infrastructure" in result["fields"]

    # Verify persisted via fresh query
    stmt = select(ProductTechStack).where(
        ProductTechStack.product_id == product_a.id,
        ProductTechStack.tenant_key == tenant_a,
    )
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.programming_languages == "Python, TypeScript"
    assert row.databases_storage == "PostgreSQL, Redis"
    assert row.infrastructure == "Docker, Kubernetes"


@pytest.mark.asyncio
async def test_write_product_architecture(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """Writes architecture fields to product_architectures table."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        architecture_pattern="Microservices",
        api_style="REST + GraphQL",
        design_patterns="CQRS, Event Sourcing",
        coding_conventions="PEP 8, 200-line function limit",
    )

    assert result["success"] is True
    assert "architecture_pattern" in result["fields"]
    assert "coding_conventions" in result["fields"]

    stmt = select(ProductArchitecture).where(
        ProductArchitecture.product_id == product_a.id,
        ProductArchitecture.tenant_key == tenant_a,
    )
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.primary_pattern == "Microservices"
    assert row.api_style == "REST + GraphQL"
    assert row.design_patterns == "CQRS, Event Sourcing"
    assert row.coding_conventions == "PEP 8, 200-line function limit"


@pytest.mark.asyncio
async def test_write_product_test_config(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """Writes test config fields to product_test_configs table."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        quality_standards="High reliability, zero downtime",
        testing_strategy="TDD",
        testing_frameworks="pytest, Jest",
        test_coverage_target=90,
    )

    assert result["success"] is True
    assert "quality_standards" in result["fields"]

    stmt = select(ProductTestConfig).where(
        ProductTestConfig.product_id == product_a.id,
        ProductTestConfig.tenant_key == tenant_a,
    )
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.quality_standards == "High reliability, zero downtime"
    assert row.test_strategy == "TDD"
    assert row.testing_frameworks == "pytest, Jest"
    assert row.coverage_target == 90


@pytest.mark.asyncio
async def test_write_product_partial_fields(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """Only provided fields are written; missing fields remain untouched (merge-write)."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    # First write: set programming_languages and frontend_frameworks
    await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        programming_languages="Python",
        frontend_frameworks="Vue 3",
    )

    # Second write: only update programming_languages
    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        force=True,
        programming_languages="Python, Rust",
    )

    assert result["fields_written"] == 1

    # Verify frontend_frameworks was NOT blanked
    stmt = select(ProductTechStack).where(
        ProductTechStack.product_id == product_a.id,
        ProductTechStack.tenant_key == tenant_a,
    )
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.programming_languages == "Python, Rust"
    assert row.frontend_frameworks == "Vue 3"


@pytest.mark.asyncio
async def test_write_product_tenant_isolation(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    tenant_b: str,
    product_b: Product,
):
    """Cannot write to another tenant's product."""
    from giljo_mcp.database import tenant_session_context
    from giljo_mcp.exceptions import ResourceNotFoundError
    from giljo_mcp.tools.vision_analysis import update_product_fields

    with pytest.raises(ResourceNotFoundError):
        with tenant_session_context(db_session, tenant_a):
            await update_product_fields(
                product_id=product_b.id,
                tenant_key=tenant_a,
                _test_session=db_session,
                product_name="Hacked Name",
            )


@pytest.mark.asyncio
async def test_write_product_websocket_event(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """WebSocket notification is emitted after successful write."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    mock_ws = AsyncMock()

    # force=True: product_a already has a name and product_name is user-owned
    # (BE-9164), so an unforced write would be skipped and emit no event.
    await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        websocket_manager=mock_ws,
        force=True,
        product_name="WS Test Product",
    )

    mock_ws.broadcast_event_to_tenant.assert_called_once()
    call_kwargs = mock_ws.broadcast_event_to_tenant.call_args[1]
    assert call_kwargs["tenant_key"] == tenant_a
    event = call_kwargs["event"]
    assert event["type"] == "vision:analysis_complete"
    assert event["data"]["product_id"] == product_a.id
    assert event["data"]["fields_written"] == 1


@pytest.mark.asyncio
async def test_write_product_target_platforms(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """target_platforms writes to the ARRAY column on the products table."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        target_platforms=["windows", "linux"],
    )

    assert result["success"] is True
    assert "target_platforms" in result["fields"]

    await db_session.refresh(product_a)
    assert product_a.target_platforms == ["windows", "linux"]


@pytest.mark.asyncio
async def test_write_product_extraction_custom_instructions(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """BE-9502a: extraction_custom_instructions writes via update_product_context.

    Was previously PUT /products/{id}-only (annex Section D#4) -- ProductService
    already had the column in its allowlist, but the field was never reachable
    from FIELD_MAP / product_field_map's PRODUCT_DIRECT_FIELDS, so no MCP path
    could correct it post-creation.
    """
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        extraction_custom_instructions="Focus on backend architecture.",
    )

    assert result["success"] is True
    assert "extraction_custom_instructions" in result["fields"]

    await db_session.refresh(product_a)
    assert product_a.extraction_custom_instructions == "Focus on backend architecture."


@pytest.mark.asyncio
async def test_write_product_invalid_testing_strategy(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """Invalid testing_strategy raises ValidationError before any DB access."""
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.tools.vision_analysis import update_product_fields

    with pytest.raises(ValidationError, match="testing_strategy"):
        await update_product_fields(
            product_id=product_a.id,
            tenant_key=tenant_a,
            _test_session=db_session,
            testing_strategy="Waterfall",
        )


@pytest.mark.asyncio
async def test_write_product_invalid_coverage_target(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """test_coverage_target outside 0-100 raises ValidationError before any DB access."""
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.tools.vision_analysis import update_product_fields

    with pytest.raises(ValidationError, match="test_coverage_target"):
        await update_product_fields(
            product_id=product_a.id,
            tenant_key=tenant_a,
            _test_session=db_session,
            test_coverage_target=150,
        )


# ---------------------------------------------------------------------------
# BE-9164: instruction placement, single-chunk inlining, product-name ownership,
# validator bound, and prompt content.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_instructions_only_on_metadata_not_chunk(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
    doc_a: VisionDocument,
    doc_a2: VisionDocument,
):
    """extraction_instructions ride only the metadata call, never a chunk response."""
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    meta = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
    )
    # Two active docs -> two chunks (raw fallback = one chunk per doc).
    assert meta["total_chunks"] == 2
    assert "extraction_instructions" in meta

    chunk = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        chunk=1,
        _test_session=db_session,
    )
    assert "extraction_instructions" not in chunk
    assert chunk["chunk"] == 1
    assert "content" in chunk
    assert chunk["write_tool"] == "update_product_context"


@pytest.mark.asyncio
async def test_single_chunk_metadata_inlines_content(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
    doc_a: VisionDocument,
):
    """Single-chunk doc: metadata call inlines the content, no follow-up call needed."""
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    meta = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
    )
    assert meta["total_chunks"] == 1
    assert meta["chunk"] == 1
    assert "content" in meta
    assert "vision document content" in meta["content"]
    assert "extraction_instructions" in meta
    assert "no further" in meta["usage"].lower()


@pytest.mark.asyncio
async def test_multi_chunk_metadata_has_no_inline_content(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
    doc_a: VisionDocument,
    doc_a2: VisionDocument,
):
    """Multi-chunk doc: metadata call carries no inline content."""
    from giljo_mcp.tools.vision_analysis import get_vision_doc as get_vision_document

    meta = await get_vision_document(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
    )
    assert meta["total_chunks"] == 2
    assert "content" not in meta
    assert "chunk" not in meta


@pytest.mark.asyncio
async def test_product_name_skipped_when_already_set(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """product_name is user-owned: skipped with a fields_skipped entry when a name exists."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        product_name="Agent Renamed",
    )

    assert "product_name" not in result["fields"]
    skipped = {s["field"]: s for s in result["fields_skipped"]}
    assert "product_name" in skipped
    assert "user-owned" in skipped["product_name"]["reason"]

    await db_session.refresh(product_a)
    assert product_a.name == "Test Product A"


@pytest.mark.asyncio
async def test_product_name_written_when_empty(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
):
    """product_name writes normally when the product currently has no name."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    product = Product(
        id=str(uuid.uuid4()),
        name="",
        tenant_key=tenant_a,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    result = await update_product_fields(
        product_id=product.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        product_name="Fresh Name",
    )

    assert "product_name" in result["fields"]
    await db_session.refresh(product)
    assert product.name == "Fresh Name"


@pytest.mark.asyncio
async def test_product_name_force_overwrites(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """force=True overwrites an existing user-owned name."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        force=True,
        product_name="Forced Name",
    )

    assert "product_name" in result["fields"]
    await db_session.refresh(product_a)
    assert product_a.name == "Forced Name"


# ---------------------------------------------------------------------------
# BE-9167: project_path (the user's local codebase folder) is filled by the
# vision-analysis agent, and is user-owned exactly like product_name.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_path_written_when_blank(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
    product_a: Product,
):
    """project_path writes to the products column when currently empty."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=product_a.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        project_path="/home/user/acme-repo",
    )

    assert "project_path" in result["fields"]
    await db_session.refresh(product_a)
    assert product_a.project_path == "/home/user/acme-repo"


@pytest.mark.asyncio
async def test_project_path_skipped_when_already_set(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
):
    """project_path is user-owned: skipped with a fields_skipped entry when already set."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    product = Product(
        id=str(uuid.uuid4()),
        name="Has Path",
        tenant_key=tenant_a,
        is_active=True,
        product_memory={},
        project_path="/existing/codebase",
    )
    db_session.add(product)
    await db_session.flush()

    result = await update_product_fields(
        product_id=product.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        project_path="/agent/guessed/path",
    )

    assert "project_path" not in result["fields"]
    skipped = {s["field"]: s for s in result["fields_skipped"]}
    assert "project_path" in skipped
    assert skipped["project_path"]["reason"] == "codebase folder is user-owned and already set"
    assert "force=True" in skipped["project_path"]["hint"]

    await db_session.refresh(product)
    assert product.project_path == "/existing/codebase"


@pytest.mark.asyncio
async def test_project_path_force_overwrites(
    db_session: AsyncSession,
    db_manager,
    tenant_a: str,
):
    """force=True overwrites an existing user-owned project_path."""
    from giljo_mcp.tools.vision_analysis import update_product_fields

    product = Product(
        id=str(uuid.uuid4()),
        name="Has Path",
        tenant_key=tenant_a,
        is_active=True,
        product_memory={},
        project_path="/old/path",
    )
    db_session.add(product)
    await db_session.flush()

    result = await update_product_fields(
        product_id=product.id,
        tenant_key=tenant_a,
        _test_session=db_session,
        force=True,
        project_path="/forced/path",
    )

    assert "project_path" in result["fields"]
    await db_session.refresh(product)
    assert product.project_path == "/forced/path"


def test_vision_extraction_prompt_has_project_path_omit_guard():
    """VISION_EXTRACTION_PROMPT teaches project_path as a top-level param with the
    omit-if-no-filesystem-access guard (BE-9167)."""
    from giljo_mcp.tools.vision_analysis import VISION_EXTRACTION_PROMPT

    assert "project_path" in VISION_EXTRACTION_PROMPT
    # Named as a top-level param in the example call shape.
    assert 'project_path="..."' in VISION_EXTRACTION_PROMPT
    # The omit-guard wording is present.
    assert "OMIT it" in VISION_EXTRACTION_PROMPT
    assert "never invent or guess a path" in VISION_EXTRACTION_PROMPT


def test_validate_vision_summaries_bound():
    """Bound raised to 500K (BE-9164): 60K accepted, 500_001 rejected."""
    from giljo_mcp.schemas.jsonb_validators import validate_vision_summaries

    doc_id = str(uuid.uuid4())
    ok = validate_vision_summaries([{"doc_id": doc_id, "light": "a" * 60_000, "medium": "b" * 60_000}])
    assert ok is not None
    assert len(ok[0]["light"]) == 60_000

    with pytest.raises(Exception):
        validate_vision_summaries([{"doc_id": doc_id, "light": "a" * 500_001, "medium": "ok"}])


def test_vision_extraction_prompt_content():
    """Prompt teaches the grouped-dict shape and two roles, not the old flat schema."""
    from giljo_mcp.tools.vision_analysis import VISION_EXTRACTION_PROMPT

    assert "tech_stack={" in VISION_EXTRACTION_PROMPT
    assert "architecture={" in VISION_EXTRACTION_PROMPT
    assert "PRODUCT MANAGER" in VISION_EXTRACTION_PROMPT
    assert "ENGINEERING MANAGER" in VISION_EXTRACTION_PROMPT
    # No stale flat-schema instruction.
    assert "call the update_product_context tool with all fields" not in VISION_EXTRACTION_PROMPT
