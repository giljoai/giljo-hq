# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

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
from giljo_mcp.tenant import TenantManager


@pytest_asyncio.fixture
async def fe9320_tenant() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def fe9320_product(db_session: AsyncSession, fe9320_tenant: str) -> Product:
    product = Product(
        id=str(uuid.uuid4()),
        name="FE-9320 Product",
        description="Product for the writable-fields regression suite.",
        tenant_key=fe9320_tenant,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _tech_stack(session: AsyncSession, product: Product, tenant_key: str) -> ProductTechStack | None:
    stmt = select(ProductTechStack).where(
        ProductTechStack.product_id == product.id,
        ProductTechStack.tenant_key == tenant_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()




@pytest.mark.asyncio
async def test_repair_write_lands_empty_columns_in_a_populated_block(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    first = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Python",
    )
    assert "programming_languages" in first["fields"]

    second = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        infrastructure="Docker, Railway",
    )

    assert "infrastructure" in second["fields"], (
        f"an EMPTY column in a populated block must still write; skipped={second['fields_skipped']}"
    )
    assert second["fields_skipped"] == [], "nothing collided -- nothing may be reported as skipped"

    row = await _tech_stack(db_session, fe9320_product, fe9320_tenant)
    assert row is not None
    assert row.infrastructure == "Docker, Railway"
    assert row.programming_languages == "Python", "the already-populated column must be left alone"


@pytest.mark.asyncio
async def test_repair_write_splits_populated_from_empty_within_one_block(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Python",
    )

    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Rust",
        infrastructure="Docker",
    )

    assert "infrastructure" in result["fields"]
    assert "programming_languages" not in result["fields"]
    skipped = {entry["field"] for entry in result["fields_skipped"]}
    assert skipped == {"programming_languages"}, f"only the colliding COLUMN may be skipped, got {skipped}"

    row = await _tech_stack(db_session, fe9320_product, fe9320_tenant)
    assert row.programming_languages == "Python"
    assert row.infrastructure == "Docker"


@pytest.mark.asyncio
async def test_repair_write_preserves_empty_columns_across_all_three_blocks(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Python",
        architecture_pattern="Layered",
        testing_strategy="TDD",
    )

    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        databases="PostgreSQL",
        coding_conventions="PEP 8, 200-line function limit",
        testing_frameworks="pytest, Vitest",
    )

    assert result["fields_skipped"] == []
    for field in ("databases", "coding_conventions", "testing_frameworks"):
        assert field in result["fields"], f"{field} was empty and must have landed"

    ts = await _tech_stack(db_session, fe9320_product, fe9320_tenant)
    assert ts.databases_storage == "PostgreSQL"
    assert ts.programming_languages == "Python"

    arch = (
        await db_session.execute(
            select(ProductArchitecture).where(
                ProductArchitecture.product_id == fe9320_product.id,
                ProductArchitecture.tenant_key == fe9320_tenant,
            )
        )
    ).scalar_one_or_none()
    assert arch.coding_conventions == "PEP 8, 200-line function limit"
    assert arch.primary_pattern == "Layered"

    tc = (
        await db_session.execute(
            select(ProductTestConfig).where(
                ProductTestConfig.product_id == fe9320_product.id,
                ProductTestConfig.tenant_key == fe9320_tenant,
            )
        )
    ).scalar_one_or_none()
    assert tc.testing_frameworks == "pytest, Vitest"
    assert tc.test_strategy == "TDD"


@pytest.mark.asyncio
async def test_force_still_overwrites_a_populated_column(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Python",
    )
    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        force=True,
        programming_languages="Rust",
    )

    assert "programming_languages" in result["fields"]
    assert result["fields_skipped"] == []
    row = await _tech_stack(db_session, fe9320_product, fe9320_tenant)
    assert row.programming_languages == "Rust"




@pytest.mark.asyncio
async def test_dev_tools_is_writable(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        dev_tools="Docker Desktop, pytest, ruff, Vite",
    )

    assert "dev_tools" in result["fields"]
    row = await _tech_stack(db_session, fe9320_product, fe9320_tenant)
    assert row is not None
    assert row.dev_tools == "Docker Desktop, pytest, ruff, Vite"


def test_every_writable_product_card_column_has_an_extraction_field():
    from giljo_mcp.services.product_field_map import RELATION_BLOCK_FIELDS
    from giljo_mcp.tools.vision_analysis import FIELD_MAP

    reachable = {(block, column) for block, column in FIELD_MAP.values()}
    for block, columns in RELATION_BLOCK_FIELDS.items():
        for column in columns:
            assert (block, column) in reachable, (
                f"{block}.{column} is a real product-card column with no extraction field -- "
                f"content for it has nowhere to land"
            )




@pytest.mark.asyncio
async def test_unmatched_vision_summary_doc_id_is_reported_to_the_caller(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=fe9320_tenant,
        product_id=fe9320_product.id,
        document_name="Vision.md",
        document_type="vision",
        vision_document="Vision content for FE-9320.",
        storage_type="inline",
        content_hash="fe9320hash",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()

    ghost_id = str(uuid.uuid4())
    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        vision_summaries=[
            {"doc_id": doc.id, "light": "Light summary.", "medium": "Medium summary."},
            {"doc_id": ghost_id, "light": "Orphan light.", "medium": "Orphan medium."},
        ],
    )

    assert "vision_summaries" in result["fields"], "the doc that DID match still landed"
    misses = [entry for entry in result["fields_skipped"] if entry["field"] == "vision_summaries"]
    assert len(misses) == 1, f"the unmatched doc_id must be reported, got {result['fields_skipped']}"
    assert misses[0]["doc_id"] == ghost_id
    assert misses[0]["reason"], "a miss must carry a reason, not just a doc_id"

    await db_session.refresh(doc)
    assert doc.summary_light == "Light summary."


@pytest.mark.asyncio
async def test_vision_summary_for_another_product_is_reported_not_silently_dropped(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    other = Product(
        id=str(uuid.uuid4()),
        name="FE-9320 Other Product",
        tenant_key=fe9320_tenant,
        is_active=False,
        product_memory={},
    )
    db_session.add(other)
    await db_session.flush()
    other_doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=fe9320_tenant,
        product_id=other.id,
        document_name="Other.md",
        document_type="vision",
        vision_document="Content belonging to another product.",
        storage_type="inline",
        content_hash="fe9320other",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(other_doc)
    await db_session.flush()

    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        vision_summaries=[{"doc_id": other_doc.id, "light": "Light.", "medium": "Medium."}],
    )

    assert "vision_summaries" not in result["fields"], "nothing landed, so nothing may be claimed as written"
    misses = [entry for entry in result["fields_skipped"] if entry["field"] == "vision_summaries"]
    assert len(misses) == 1
    assert misses[0]["doc_id"] == other_doc.id




@pytest.mark.asyncio
async def test_response_reports_completion_state_and_what_is_missing(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.tools.vision_analysis import update_product_fields

    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=fe9320_tenant,
        product_id=fe9320_product.id,
        document_name="Vision.md",
        document_type="vision",
        vision_document="Vision content.",
        storage_type="inline",
        content_hash="fe9320stage",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    db_session.add(doc)
    await db_session.flush()

    stage_one = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Python",
    )
    assert stage_one["vision_analysis_complete"] is False
    assert stage_one["missing_for_completion"], "an incomplete analysis must say what is missing"

    stage_two = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        vision_summaries=[{"doc_id": doc.id, "light": "Light.", "medium": "Medium."}],
    )
    assert stage_two["vision_analysis_complete"] is False
    assert any("consolidated" in reason for reason in stage_two["missing_for_completion"])

    stage_three = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        emit_completion=True,
        consolidated_vision={"light": "Consolidated light.", "medium": "Consolidated medium."},
    )
    assert stage_three["vision_analysis_complete"] is True
    assert stage_three["missing_for_completion"] == []

    await db_session.refresh(fe9320_product)
    assert fe9320_product.vision_analysis_complete is True


@pytest.mark.asyncio
async def test_emit_completion_emits_even_when_the_final_call_writes_nothing(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from unittest.mock import AsyncMock

    from giljo_mcp.tools.vision_analysis import update_product_fields

    ws = AsyncMock()
    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        websocket_manager=ws,
        emit_completion=True,
    )

    assert result["success"] is True
    assert result["fields"] == []
    ws.broadcast_event_to_tenant.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_write_websocket_emit_survives_for_progressive_fill(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from unittest.mock import AsyncMock

    from giljo_mcp.tools.vision_analysis import update_product_fields

    ws = AsyncMock()
    result = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        websocket_manager=ws,
        programming_languages="Python",
    )

    assert result["vision_analysis_complete"] is False
    ws.broadcast_event_to_tenant.assert_awaited_once()




@pytest.mark.asyncio
async def test_over_length_project_path_is_a_clean_rejection_not_an_opaque_500(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.product_service import ProductService

    service = ProductService(db_manager=None, tenant_key=fe9320_tenant, test_session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.update_product(fe9320_product.id, force=True, project_path="/srv/" + "x" * 600)

    assert "500" in exc_info.value.message
    assert "project_path" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_project_path_at_the_limit_still_writes(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    from giljo_mcp.services.product_service import ProductService

    service = ProductService(db_manager=None, tenant_key=fe9320_tenant, test_session=db_session)
    legal = "/srv/" + "x" * 495

    await service.update_product(fe9320_product.id, force=True, project_path=legal)

    await db_session.refresh(fe9320_product)
    assert fe9320_product.project_path == legal


@pytest.mark.asyncio
async def test_create_product_rejects_an_over_length_project_path(
    db_session: AsyncSession,
    fe9320_tenant: str,
):
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.product_service import ProductService

    service = ProductService(db_manager=None, tenant_key=fe9320_tenant, test_session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.create_product(name="FE-9320 create guard", project_path="/srv/" + "x" * 600)

    assert "project_path" in exc_info.value.message.lower()


def test_product_create_still_accepts_a_blank_name_on_purpose():
    from api.endpoints.products.models import ProductCreate

    assert ProductCreate(name="").name == ""
    assert ProductCreate(name="Real Product").name == "Real Product"
