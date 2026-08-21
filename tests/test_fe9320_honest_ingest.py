# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9320 — every product-card field is writable, and the ingest is honest.

Four defects, each tested at the layer it lives on:

1. ``dev_tools`` is a real ``product_tech_stacks`` column that no extraction field
   could reach, so content about tooling had nowhere to land but
   ``architecture_notes``.
2. **The museum-rule item.** Overwrite protection guarded on the relation ROW
   existing (``product.tech_stack is not None``) rather than on the COLUMN holding
   a value. The row is created on the first write, so every later repair call had
   its whole block stripped -- discarding columns that were still EMPTY.
   ``test_repair_write_lands_empty_columns_in_a_populated_block`` reproduces that
   loss and FAILED before the guard became per-column.
3. ``vision_summaries`` dropped an unmatched ``doc_id`` with a log line while
   telling the caller ``vision_summaries`` was written -- the only true silent data
   loss in the ingest.
4. The extraction spec mandated ONE call covering everything (a real run died at
   62,420 bytes) and the caller had to INFER whether the completion flag flipped.

Parallel-safe: every test takes the rolled-back ``db_session``, generates its own
tenant key, and owns its own setup. No module-level mutable state.
"""

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


# ---------------------------------------------------------------------------
# Item 2 -- MUSEUM RULE. Written and watched FAIL on the block-level guard
# before the guard was changed to per-column.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_write_lands_empty_columns_in_a_populated_block(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    """FAIL-FIRST. First call fills ONE tech_stack column. A second call carrying a
    DIFFERENT, still-empty column of the same block must land it.

    On the block-level guard this failed: the first write created the relation row,
    so ``product.tech_stack is not None`` reported the whole block "already
    populated", the tool stripped the entire block, and ``infrastructure`` -- which
    held nothing at all -- was silently discarded.
    """
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
    """A mixed repair call: one column collides, one is empty. The empty one lands,
    the populated one is skipped BY NAME (not as a whole block) and keeps its value."""
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
    """The same loss applied to architecture (incl. coding_conventions) and
    test_config. One repair call must fill every still-empty column in all three."""
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
    """The load-bearing HAPPY half: force=True still overwrites, and the per-column
    guard did not quietly become a no-op that lets every write through."""
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


# ---------------------------------------------------------------------------
# Item 1 -- dev_tools is writable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_tools_is_writable(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    """dev_tools is a real column; content about tooling must land THERE, not be
    forced into architecture_notes for lack of an extraction field."""
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
    """DoD 1: no product-card column may be unreachable from the extraction path.

    Locks the gap that made dev_tools unwritable -- a column added to a relation
    block with no FIELD_MAP entry trips this instead of silently having nowhere to
    land. ``products.quality_standards`` is excluded because it is dead: the field
    routes to test_config and the read path uses ``tc.quality_standards``.
    """
    from giljo_mcp.services.product_field_map import RELATION_BLOCK_FIELDS
    from giljo_mcp.tools.vision_analysis import FIELD_MAP

    reachable = {(block, column) for block, column in FIELD_MAP.values()}
    for block, columns in RELATION_BLOCK_FIELDS.items():
        for column in columns:
            assert (block, column) in reachable, (
                f"{block}.{column} is a real product-card column with no extraction field -- "
                f"content for it has nowhere to land"
            )


# ---------------------------------------------------------------------------
# Item 3 -- vision_summaries misses are REPORTED, never silently dropped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unmatched_vision_summary_doc_id_is_reported_to_the_caller(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    """An unknown doc_id used to vanish into a log line while the response still
    said vision_summaries was written. It must come back as a named skip."""
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
    """A doc_id that exists for this tenant but belongs to a DIFFERENT product is
    the second silent-drop branch -- it must be reported with its own reason."""
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


# ---------------------------------------------------------------------------
# Item 4 -- staged writes: the caller is TOLD the completion state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_reports_completion_state_and_what_is_missing(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    """A staged call must not force the agent to INFER whether the flag flipped.
    Every response carries vision_analysis_complete + missing_for_completion."""
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

    # Stage 1: structured fields only -- nothing about summaries yet.
    stage_one = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        programming_languages="Python",
    )
    assert stage_one["vision_analysis_complete"] is False
    assert stage_one["missing_for_completion"], "an incomplete analysis must say what is missing"

    # Stage 2: the per-doc summary lands; the consolidated aggregate is still absent.
    stage_two = await update_product_fields(
        product_id=fe9320_product.id,
        tenant_key=fe9320_tenant,
        _test_session=db_session,
        vision_summaries=[{"doc_id": doc.id, "light": "Light.", "medium": "Medium."}],
    )
    assert stage_two["vision_analysis_complete"] is False
    assert any("consolidated" in reason for reason in stage_two["missing_for_completion"])

    # Stage 3: the final staged call declares completion explicitly.
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
    """The WS emit is gated on fields_written, so a pure "I am done" call was silent.
    emit_completion must still signal the wizard."""
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
    """Do NOT narrow the emit to completion only. TutorialPromptScreen.vue documents
    a ratified PROGRESSIVE-FILL contract that uses vision:analysis_complete as
    a per-write refresh tick -- a section write with the flag still false must emit."""
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


# ---------------------------------------------------------------------------
# Item 5 -- the two guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_length_project_path_is_a_clean_rejection_not_an_opaque_500(
    db_session: AsyncSession,
    fe9320_tenant: str,
    fe9320_product: Product,
):
    """project_path is String(500) at the DB and 20000 at the tool boundary, with no
    service guard in between -- an over-length value became a sanitized 500."""
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
    """Two-sided: the guard must reject over-length WITHOUT breaking a legal path."""
    from giljo_mcp.services.product_service import ProductService

    service = ProductService(db_manager=None, tenant_key=fe9320_tenant, test_session=db_session)
    legal = "/srv/" + "x" * 495  # exactly 500

    await service.update_product(fe9320_product.id, force=True, project_path=legal)

    await db_session.refresh(fe9320_product)
    assert fe9320_product.project_path == legal


@pytest.mark.asyncio
async def test_create_product_rejects_an_over_length_project_path(
    db_session: AsyncSession,
    fe9320_tenant: str,
):
    """Same column, same cap, other write path -- create must not 500 either."""
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.product_service import ProductService

    service = ProductService(db_manager=None, tenant_key=fe9320_tenant, test_session=db_session)

    with pytest.raises(ValidationError) as exc_info:
        await service.create_product(name="FE-9320 create guard", project_path="/srv/" + "x" * 600)

    assert "project_path" in exc_info.value.message.lower()


def test_product_create_still_accepts_a_blank_name_on_purpose():
    """The nameless-product fix does NOT belong at creation, and this locks that.

    FE-9320 originally planned a min_length here; that was refuted with evidence and
    ruled out: the onboarding "existing codebase" door pre-creates a nameless
    draft precisely so the agent can name it, because update_product_context writes
    product_name ONLY while the existing name is blank and skips it once non-empty
    (tests/test_fe9200_tutorial_prompt_contract.py). A create-time guard makes that
    door fall back to "My product", which the agent can then never rename -- strictly
    worse than the nameless row. The guard lives at ACTIVATION, in the wizard.
    """
    from api.endpoints.products.models import ProductCreate

    assert ProductCreate(name="").name == ""
    assert ProductCreate(name="Real Product").name == "Real Product"
