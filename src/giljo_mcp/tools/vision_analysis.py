# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP Tools: get_vision_doc and update_product_context (Handover 0842c)

Provides vision document retrieval with extraction prompt and structured product
field writing from AI analysis results. Called by the user's AI coding agent
during vision document analysis workflow.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.config_manager import get_config
from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.context import MCPContextIndex
from giljo_mcp.models.products import (
    Product,
    VisionDocument,
)
from giljo_mcp.repositories.vision_document_repository import VisionDocumentRepository
from giljo_mcp.schemas.jsonb_validators import (
    validate_consolidated_vision,
    validate_vision_summaries,
)
from giljo_mcp.security.upload_guard import (
    TEXT_EXTENSIONS,
    UploadFilenameError,
    sanitize_upload_filename,
)
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.services.product_field_map import assemble_update_kwargs
from giljo_mcp.services.product_vision_service import ProductVisionService
from giljo_mcp.tools._unknown_keys import split_known
from giljo_mcp.tools.product_activation import apply_activation_state
from giljo_mcp.tools.vision_extraction_prompt import VISION_EXTRACTION_PROMPT


logger = logging.getLogger(__name__)


# VISION_EXTRACTION_PROMPT is imported above from tools/vision_extraction_prompt.py (see
# that module for why); get_vision_doc returns it as extraction_instructions, and the
# import keeps `from ...vision_analysis import VISION_EXTRACTION_PROMPT` resolving.


VALID_TESTING_STRATEGIES = {"TDD", "BDD", "Integration-First", "E2E-First", "Manual", "Hybrid"}

FIELD_MAP = {
    "product_name": ("products", "name"),
    "product_description": ("products", "description"),
    "project_path": ("products", "project_path"),
    "core_features": ("products", "core_features"),
    "programming_languages": ("tech_stack", "programming_languages"),
    "frontend_frameworks": ("tech_stack", "frontend_frameworks"),
    "backend_frameworks": ("tech_stack", "backend_frameworks"),
    "databases": ("tech_stack", "databases_storage"),
    "infrastructure": ("tech_stack", "infrastructure"),
    "dev_tools": ("tech_stack", "dev_tools"),
    "target_platforms": ("products", "target_platforms"),
    "architecture_pattern": ("architecture", "primary_pattern"),
    "design_patterns": ("architecture", "design_patterns"),
    "api_style": ("architecture", "api_style"),
    "architecture_notes": ("architecture", "architecture_notes"),
    "coding_conventions": ("architecture", "coding_conventions"),
    "brand_guidelines": ("products", "brand_guidelines"),
    "extraction_custom_instructions": ("products", "extraction_custom_instructions"),
    "quality_standards": ("test_config", "quality_standards"),
    "testing_strategy": ("test_config", "test_strategy"),
    "testing_frameworks": ("test_config", "testing_frameworks"),
    "test_coverage_target": ("test_config", "coverage_target"),
}

# Reverse of FIELD_MAP: (block, column) -> extraction field name. Used by the
# overwrite-protection rollback below to name the exact extraction field behind a
# skipped COLUMN. (The column->block grouping itself lives in the shared
# product-field translator, services/product_field_map.py.)
_FIELD_FOR_COLUMN = {target: field_name for field_name, target in FIELD_MAP.items()}


@asynccontextmanager
async def _session_scope(
    db_manager: DatabaseManager | None,
    test_session: AsyncSession | None,
):
    """Yield the test session directly or open a new managed session."""
    if test_session is not None:
        yield test_session
    else:
        async with db_manager.get_session_async() as session:
            yield session


async def get_vision_doc(
    product_id: str,
    tenant_key: str,
    chunk: int | None = None,
    db_manager: DatabaseManager | None = None,
    websocket_manager: Any = None,
    _test_session: AsyncSession | None = None,
) -> dict[str, Any]:
    """
    Retrieve vision document content as paginated chunks with extraction instructions.

    Call with no chunk parameter to get metadata (total_chunks, extraction_instructions).
    Then fetch chunk=1..total_chunks. Chunk reads are independent and side-effect free,
    so they can be requested in PARALLEL -- there is no ordering requirement (FE-9320:
    the old "chunk=1, chunk=2, etc." phrasing read as sequential and cost a real run six
    round trips for one document).

    Args:
        product_id: Target product UUID
        tenant_key: Tenant isolation key
        chunk: 1-based chunk number to retrieve. Omit for metadata only.
        db_manager: Injected by ToolAccessor

    Returns:
        Without chunk param: metadata (total_chunks, total_tokens, extraction_instructions, etc.)
        With chunk param: single chunk content + metadata

    Raises:
        ResourceNotFoundError: If product not found or has no vision documents
    """
    if not db_manager and _test_session is None:
        raise ValueError("db_manager is required")

    async with _session_scope(db_manager, _test_session) as session:
        stmt = (
            select(Product)
            .where(Product.id == product_id, Product.tenant_key == tenant_key)
            .options(selectinload(Product.vision_documents))
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            raise ResourceNotFoundError(
                f"Product {product_id} not found for tenant",
                context={"product_id": product_id},
            )

        # BE-6130b: the vision_documents relationship loads trashed rows too;
        # exclude soft-deleted docs (deleted_at) alongside the is_active filter.
        active_docs = [doc for doc in product.vision_documents if doc.is_active and doc.deleted_at is None]

        if not active_docs:
            raise ResourceNotFoundError(
                "No vision documents found for this product",
                context={"product_id": product_id},
            )

        # Collect vision_document_ids for chunk lookup
        doc_ids = [str(doc.id) for doc in active_docs]

        # Query pre-chunked content from mcp_context_index, ordered by chunk_order
        chunk_stmt = (
            select(MCPContextIndex)
            .where(
                MCPContextIndex.product_id == product_id,
                MCPContextIndex.tenant_key == tenant_key,
                MCPContextIndex.vision_document_id.in_(doc_ids),
            )
            .order_by(MCPContextIndex.vision_document_id, MCPContextIndex.chunk_order)
        )
        chunk_result = await session.execute(chunk_stmt)
        all_chunks = chunk_result.scalars().all()

        if not all_chunks:
            # Fallback: document exists but hasn't been chunked yet — use raw content.
            # BE-5117b: preserve per-doc identity so the agent can map chunks back
            # to vision_summaries[].doc_id when writing summaries.
            logger.warning("No chunks found for product %s, falling back to raw document", product_id)
            raw_pairs = [(str(doc.id), doc.vision_document) for doc in active_docs if doc.vision_document]
        else:
            raw_pairs = [(str(c.vision_document_id), c.content) for c in all_chunks]

        # Sub-split any chunks >25K chars so each fits within MCP tool output limits.
        max_chars = 25000
        split_pairs: list[tuple[str, str]] = []
        for doc_id_value, raw in raw_pairs:
            if len(raw) <= max_chars:
                split_pairs.append((doc_id_value, raw))
            else:
                # Split on paragraph boundaries where possible
                split_pairs.extend((doc_id_value, raw[i : i + max_chars]) for i in range(0, len(raw), max_chars))

        chunk_list = [
            {
                "chunk_order": i + 1,
                "doc_id": doc_id_value,
                "content": text,
                "token_count": len(text.split()),
            }
            for i, (doc_id_value, text) in enumerate(split_pairs)
        ]

        total_chunks = len(chunk_list)
        total_tokens = sum(c["token_count"] for c in chunk_list)

        active_doc_ids = [str(doc.id) for doc in active_docs]

        if chunk is not None:
            # -- Single-chunk retrieval: minimal routing payload. The extraction
            #    instructions are NOT re-sent on chunk responses (BE-9164): they
            #    ride only on the metadata call to avoid resending the prompt on
            #    every chunk. --
            if chunk < 1 or chunk > total_chunks:
                raise ResourceNotFoundError(
                    f"Chunk {chunk} not found (valid range: 1-{total_chunks})",
                    context={"product_id": product_id, "chunk": chunk, "total_chunks": total_chunks},
                )
            selected = chunk_list[chunk - 1]
            return {
                "chunk": chunk,
                "doc_id": selected["doc_id"],
                "content": selected["content"],
                "chunk_token_count": selected["token_count"],
                "total_chunks": total_chunks,
                "product_id": product_id,
                "write_tool": "update_product_context",
            }

        # -- Metadata call (chunk is None): carries the extraction_instructions. --
        custom_instructions = product.extraction_custom_instructions or ""
        extraction_instructions = VISION_EXTRACTION_PROMPT.replace("{custom_instructions}", custom_instructions)
        base = {
            "total_chunks": total_chunks,
            "total_tokens": total_tokens,
            "extraction_instructions": extraction_instructions,
            "write_tool": "update_product_context",
            "product_id": product_id,
            "product_name": product.name,
            "doc_ids": active_doc_ids,
        }

        if total_chunks == 1:
            # BE-9164: single-chunk docs need no follow-up call. Inline the only
            # chunk's content directly in the metadata response.
            only = chunk_list[0]
            base["chunk"] = 1
            base["doc_id"] = only["doc_id"]
            base["content"] = only["content"]
            base["chunk_token_count"] = only["token_count"]
            base["usage"] = "All content is included above; no further get_vision_document calls are needed."
        else:
            # Metadata only — no content, agent should request the chunks.
            base["usage"] = (
                f"Fetch chunk=1 through chunk={total_chunks} to retrieve content. These reads are "
                "independent and side-effect free -- request them in PARALLEL, in any order."
            )

        # Notify frontend that the agent has connected and started analysis
        if websocket_manager and chunk is None:
            from giljo_mcp.events.schemas import EventFactory

            event = EventFactory.tenant_envelope(
                event_type="vision:analysis_started",
                tenant_key=tenant_key,
                data={"product_id": product_id, "total_chunks": total_chunks},
            )
            await websocket_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

        return base


# BE-9201: default name for an agent-authored vision document (prompt D/B).
DEFAULT_AGENT_VISION_DOC_NAME = "Agent Vision.md"


async def create_vision_document(
    product_id: str,
    tenant_key: str,
    content: str,
    document_name: str = "",
    db_manager: DatabaseManager | None = None,
    _test_session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Create a vision document from agent-authored markdown (BE-9201).

    Agent-side twin of the REST upload endpoints: routes through
    ProductVisionService.upload_vision_document (the owning service both REST
    endpoints use), so the doc gets the identical ingest — inline storage,
    auto-chunking, auto-consolidation (refreshing consolidated_vision_hash, the
    staleness fingerprint in services/vision_hash.py) — and appears in the UI
    exactly like an uploaded file. Boundary validation mirrors the SEC-0001
    REST guards (minus the byte-sniff — ``content`` is a typed str): non-empty
    content, the SAME ``get_config().upload.max_upload_bytes`` cap, filename
    sanitization + ``.md`` appended when the extension is missing.

    Raises ValidationError (empty/oversize content, bad or duplicate
    document_name) or ResourceNotFoundError (product not found for tenant).
    """
    if not db_manager and _test_session is None:
        raise ValueError("db_manager is required")

    if not content or not content.strip():
        raise ValidationError(
            message="content is required and cannot be empty. Pass the full markdown vision document text.",
            context={"product_id": product_id},
        )

    max_bytes = get_config().upload.max_upload_bytes
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > max_bytes:
        raise ValidationError(
            message=f"content is {content_bytes} bytes; the maximum vision document size is "
            f"{max_bytes // 1024 // 1024} MB. Trim the document and retry.",
            context={"product_id": product_id, "max_bytes": max_bytes},
        )

    raw_name = (document_name or "").strip() or DEFAULT_AGENT_VISION_DOC_NAME
    try:
        safe_name = sanitize_upload_filename(raw_name)
    except UploadFilenameError as exc:
        raise ValidationError(
            message=f"Invalid document_name: {exc}. Use a plain filename like 'Product Vision.md'.",
            context={"product_id": product_id},
        ) from exc
    if not any(safe_name.lower().endswith(ext) for ext in TEXT_EXTENSIONS):
        safe_name = f"{safe_name}.md"

    vision_service = ProductVisionService(db_manager=db_manager, tenant_key=tenant_key, test_session=_test_session)

    # Duplicate-name pre-check mirroring the uq_vision_doc_product_name unique
    # constraint (covers trashed rows too) so the agent gets an actionable
    # rejection, not a sanitized constraint 500 (REST maps the same to a 409).
    async with tenant_scoped_session(db_manager, tenant_key, _test_session) as session:
        clash = await session.execute(
            select(VisionDocument.id).where(
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.product_id == product_id,
                VisionDocument.document_name == safe_name,
            )
        )
        if clash.first() is not None:
            raise ValidationError(
                message=f"A vision document named '{safe_name}' already exists for this product. "
                "Pass a different document_name.",
                context={"product_id": product_id, "document_name": safe_name},
            )

    result = await vision_service.upload_vision_document(product_id=product_id, content=content, filename=safe_name)

    # Parity with the REST upload (BE-5118): a fresh doc has no summaries, so
    # the completion flag must drop to FALSE until the agent writes summaries.
    # tenant_scoped_session (not bare _session_scope): the evaluator's
    # tenant-predicated select needs service-sourced tenant context.
    async with tenant_scoped_session(db_manager, tenant_key, _test_session) as session:
        await vision_service.evaluate_vision_analysis_complete(session, product_id)
        await session.commit()

    return {
        "success": True,
        "document_id": result.document_id,
        "document_name": result.document_name,
        "chunks_created": result.chunks_created,
        "total_tokens": result.total_tokens,
        "product_id": product_id,
        "next_step": "The document is ingested and visible in the dashboard. To populate the product card "
        "from it, call get_vision_document then update_product_context (including vision_summaries + consolidated_vision).",
    }


def _build_update_kwargs(
    fields: dict[str, Any],
    fields_written: list[str],
) -> dict[str, Any]:
    """Build kwargs dict for ProductService.update_product() from extracted fields.

    Translates each extracted vision field to its canonical product column via
    FIELD_MAP, then groups the columns into update_product blocks through the shared
    product-field translator (services/product_field_map.py) -- the same translator the
    context-tuning writer uses. Mutates fields_written in place to track which extraction
    fields will be written. Relation blocks are written as partial dicts;
    ProductRepository.update_config_relations merges them per-field, so only the provided
    columns are overwritten.
    """
    column_values: dict[str, Any] = {}
    for field_name, (_table, column_name) in FIELD_MAP.items():
        if field_name in fields:
            column_values[column_name] = fields[field_name]
            fields_written.append(field_name)
    return assemble_update_kwargs(column_values)


async def _apply_overwrite_protection(
    exc: ValidationError,
    product_service: Any,
    product_id: str,
    kwargs: dict[str, Any],
    fields_written: list[str],
    fields_skipped: list[dict[str, str]],
    *,
    force: bool,
) -> None:
    """Handle ProductService overwrite-protection as structured skips.

    ProductService raises ValidationError carrying
    ``context={"populated_columns": {block: [column, ...]}}`` when specific config
    COLUMNS already hold a value and force=False. Roll exactly those columns'
    extraction fields out of ``fields_written`` into ``fields_skipped``, then
    re-attempt the write with only the conflicting columns stripped. Re-raise any
    other ValidationError.

    FE-9320: this used to strip the whole BLOCK, so a repair call discarded every
    column of tech_stack / architecture / test_config -- including the ones that
    were still empty. Only the colliding columns are dropped now.
    """
    populated_columns = (exc.context or {}).get("populated_columns") if hasattr(exc, "context") else None
    if not populated_columns:
        raise exc

    safe_kwargs = dict(kwargs)
    for block, columns in populated_columns.items():
        for column in columns:
            field_name = _FIELD_FOR_COLUMN.get((block, column))
            if field_name in fields_written:
                fields_written.remove(field_name)
                fields_skipped.append(
                    {
                        "field": field_name,
                        "reason": f"{block}.{column} already has a value",
                        "hint": "Pass force=True to overwrite.",
                    }
                )
        remaining = {c: v for c, v in safe_kwargs.get(block, {}).items() if c not in columns}
        if remaining:
            safe_kwargs[block] = remaining
        else:
            safe_kwargs.pop(block, None)

    if safe_kwargs:
        await product_service.update_product(product_id, force=force, **safe_kwargs)


def _skip_user_owned_field(
    field_key: str,
    existing_value: str | None,
    fields: dict[str, Any],
    fields_skipped: list[dict[str, str]],
    *,
    label: str,
) -> None:
    """Drop a user-owned extraction field when it is already set (unless force).

    product_name (the product's name) and project_path (the user's local codebase
    folder) are both user-owned. When the product already carries a non-empty value
    the incoming extracted value is dropped from the write and recorded in
    ``fields_skipped`` so the agent sees what didn't land and why. Callers gate this
    on ``force is False``; when the existing value is empty the field writes normally.
    """
    if field_key not in fields:
        return
    if (existing_value or "").strip():
        fields.pop(field_key)
        fields_skipped.append(
            {
                "field": field_key,
                "reason": f"{label} is user-owned and already set",
                "hint": "Pass force=True to overwrite.",
            }
        )


def _validate_extraction_input(
    product_id: str,
    fields: dict[str, Any],
) -> tuple[list[dict] | None, dict | None]:
    """Validate agent input at the MCP boundary, BEFORE any DB access.

    Rejects the removed legacy summary fields, the enum-like extraction fields, and
    the two JSONB summary payloads, so bad agent input becomes a clean 422-style
    ValidationError instead of a DB-constraint 500. Pops ``vision_summaries`` /
    ``consolidated_vision`` out of ``fields`` (they are written through their own
    paths, not the column mapper) and returns them validated.
    """
    # BE-5117b: legacy summary fields were the parallel write path into
    # vision_document_summaries. That table is gone and only the column
    # path (vision_summaries / consolidated_vision) is valid. Silent no-op
    # would mask agent-prompt drift -- raise loudly so the caller sees it.
    legacy_passed = {"summary_33", "summary_66"}.intersection(fields)
    if legacy_passed:
        raise ValidationError(
            message=(
                f"Unknown fields: {sorted(legacy_passed)}. "
                "summary_33 / summary_66 were removed. Use "
                "vision_summaries=[{doc_id, light, medium}] for per-document "
                "summaries and consolidated_vision={light, medium} for the "
                "product-level aggregate."
            ),
            context={"unknown_fields": sorted(legacy_passed)},
        )

    if "testing_strategy" in fields:
        strategy = fields["testing_strategy"]
        if strategy not in VALID_TESTING_STRATEGIES:
            valid_list = ", ".join(sorted(VALID_TESTING_STRATEGIES))
            raise ValidationError(
                message=f"Invalid testing_strategy '{strategy}'. Valid values: {valid_list}",
                context={"testing_strategy": strategy},
            )

    if "test_coverage_target" in fields:
        target = fields["test_coverage_target"]
        if not isinstance(target, int) or not (0 <= target <= 100):
            raise ValidationError(
                message=f"test_coverage_target must be an integer between 0 and 100, got {target!r}",
                context={"test_coverage_target": target},
            )

    # BE-5117: type, shape, length caps, and doc_id UUID format are enforced here.
    vision_summaries_payload: list[dict] | None = None
    consolidated_vision_payload: dict | None = None
    if "vision_summaries" in fields:
        try:
            vision_summaries_payload = validate_vision_summaries(fields.pop("vision_summaries"))
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise ValidationError(
                message=f"Invalid vision_summaries payload: {exc}",
                context={"product_id": product_id},
            ) from exc
    if "consolidated_vision" in fields:
        try:
            consolidated_vision_payload = validate_consolidated_vision(fields.pop("consolidated_vision"))
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise ValidationError(
                message=f"Invalid consolidated_vision payload: {exc}",
                context={"product_id": product_id},
            ) from exc
    return vision_summaries_payload, consolidated_vision_payload


async def update_product_fields(
    product_id: str,
    tenant_key: str,
    db_manager: DatabaseManager | None = None,
    websocket_manager: Any = None,
    _test_session: AsyncSession | None = None,
    force: bool = False,
    emit_completion: bool = False,
    is_active: bool | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Write product fields extracted from vision document analysis.

    Performs merge-write: only updates fields that are explicitly provided.
    Creates child table rows (tech_stack, architecture, test_config) on first write.
    Safe to call in STAGES (FE-9320): each call writes what it carries, and every
    response reports the live completion state so the agent never has to infer
    whether the analysis finished.

    Args:
        product_id: Target product UUID
        tenant_key: Tenant isolation key
        db_manager: Injected by ToolAccessor
        websocket_manager: Injected by ToolAccessor for event emission
        emit_completion: Marks this as the FINAL staged call. Re-evaluates the
            completion flag and signals the dashboard even when this call writes no
            fields (the emit is otherwise gated on something having been written).
        is_active: BE-9502a activate/deactivate -- see product_activation.apply_activation_state.
        **fields: Extracted field key-value pairs

    Returns:
        Dict with success, fields_written count, fields list, fields_skipped,
        vision_analysis_complete and missing_for_completion.
    Raises:
        ResourceNotFoundError: If product not found for tenant
    """
    if not db_manager and _test_session is None:
        raise ValueError("db_manager is required")

    activation_result: dict[str, Any] = {}
    if is_active is not None:
        activation_result = await apply_activation_state(
            product_id, tenant_key, is_active, db_manager, websocket_manager, _test_session
        )

    vision_summaries_payload, consolidated_vision_payload = _validate_extraction_input(product_id, fields)

    fields_written: list[str] = []
    fields_skipped: list[dict[str, str]] = []

    # BE-9322: name back any field this tool cannot map (_build_update_kwargs iterates
    # FIELD_MAP, not `fields`). DEFENSIVE ONLY -- unreachable in production (the grouped
    # MCP models declare extra="forbid", so FastMCP drops unknown top-level args first).
    _mappable, unmappable_fields = split_known(fields, FIELD_MAP)
    _unmappable_hint = f"Valid fields: {', '.join(sorted(FIELD_MAP))}."
    fields_skipped.extend(
        {"field": name, "reason": "unrecognized field -- no product column maps to it", "hint": _unmappable_hint}
        for name in unmappable_fields
    )

    async with _session_scope(db_manager, _test_session) as session:
        stmt = (
            select(Product)
            .where(Product.id == product_id, Product.tenant_key == tenant_key)
            .options(
                selectinload(Product.tech_stack),
                selectinload(Product.architecture),
                selectinload(Product.test_config),
                selectinload(Product.vision_documents),
            )
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            raise ResourceNotFoundError(
                f"Product {product_id} not found for tenant",
                context={"product_id": product_id},
            )

        # BE-9164 / BE-9167: product_name and project_path (the codebase folder) are user-owned.
        # Skip each incoming value when the product already has a non-empty one, unless force=True.
        # When the existing value is empty the extracted value writes normally.
        if not force:
            _skip_user_owned_field("product_name", product.name, fields, fields_skipped, label="product name")
            _skip_user_owned_field(
                "project_path", product.project_path, fields, fields_skipped, label="codebase folder"
            )

        kwargs = _build_update_kwargs(fields, fields_written)

        # -- Route writes through ProductService (the validated single write path) --
        # Track skipped fields explicitly so the agent can see what didn't write
        # and why (instead of having to diff fields_written against their input).
        if kwargs:
            from giljo_mcp.services.product_service import ProductService

            product_service = ProductService(
                db_manager=db_manager,
                tenant_key=tenant_key,
                websocket_manager=websocket_manager,
                test_session=_test_session,
            )
            try:
                await product_service.update_product(product_id, force=force, **kwargs)
            except ValidationError as exc:
                await _apply_overwrite_protection(
                    exc,
                    product_service,
                    product_id,
                    kwargs,
                    fields_written,
                    fields_skipped,
                    force=force,
                )

        # -- BE-5117: per-doc vision_summaries + aggregate consolidated_vision --
        # Both payloads are persisted via owning services (VisionDocumentRepository
        # for per-doc, ProductService.update_product for aggregate) so the post-0962
        # owning-service routing rule holds. The completion flag is then re-evaluated
        # inside the same session/transaction.
        if vision_summaries_payload is not None:
            await _write_vision_summaries(
                vision_summaries_payload,
                tenant_key,
                session,
                product_id,
                db_manager,
                fields_written,
                fields_skipped,
            )
        if consolidated_vision_payload is not None:
            await _write_consolidated_vision(
                consolidated_vision_payload,
                tenant_key,
                product_id,
                db_manager,
                _test_session,
                fields_written,
                force=force,
            )
        # FE-9320: evaluate on EVERY call, not only when summaries were in the
        # payload. Staged writes need each response to carry the true completion
        # state -- a real run had to guess whether the flag had flipped, and guessed.
        vision_service = ProductVisionService(
            db_manager=db_manager,
            tenant_key=tenant_key,
            test_session=_test_session,
        )
        analysis_complete, missing_for_completion = await vision_service.evaluate_vision_completion(session, product_id)

    # WebSocket emission (after commit via context manager). The per-write emit is
    # load-bearing for the tutorial's progressive-fill contract (each event is a
    # refresh tick, not a completion signal), so it stays; emit_completion only ADDS
    # the case where the final staged call wrote nothing of its own.
    if websocket_manager and (fields_written or emit_completion):
        from giljo_mcp.events.schemas import EventFactory

        event = EventFactory.tenant_envelope(
            event_type="vision:analysis_complete",
            tenant_key=tenant_key,
            data={
                "product_id": product_id,
                "fields_written": len(fields_written),
                "fields": fields_written,
                "vision_analysis_complete": analysis_complete,
            },
        )
        await websocket_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

    return {
        "success": True,
        "fields_written": len(fields_written),
        "fields": fields_written,
        "fields_skipped": fields_skipped,
        "vision_analysis_complete": analysis_complete,
        "missing_for_completion": missing_for_completion,
        **activation_result,
    }


async def _write_vision_summaries(
    payload: list[dict],
    tenant_key: str,
    session: AsyncSession,
    product_id: str,
    db_manager: DatabaseManager | None,
    fields_written: list[str],
    fields_skipped: list[dict[str, str]],
) -> None:
    """Persist agent-supplied per-document light/medium summaries (BE-5117).

    Routes through VisionDocumentRepository (the owning repo for vision
    documents). Per-doc tenant scoping is enforced inside ``update_summaries``.

    FE-9320: a doc_id that matched nothing used to be dropped with only a log line
    while the response still reported ``vision_summaries`` written -- the one place
    in this ingest that lost agent data silently. Every miss is now reported to the
    caller with its doc_id and the reason it did not land.
    """
    repo = VisionDocumentRepository(db_manager=db_manager)
    landed: list[str] = []
    for entry in payload:
        updated = await repo.update_summaries(
            session=session,
            tenant_key=tenant_key,
            document_id=entry["doc_id"],
            light=entry["light"],
            medium=entry["medium"],
        )
        if updated is None:
            reason = "no vision document with this doc_id exists for this tenant"
        elif str(updated.product_id) != str(product_id):
            reason = "this doc_id belongs to a different product"
        else:
            landed.append(entry["doc_id"])
            continue
        logger.warning("vision_summaries.skip: doc_id=%s %s", entry["doc_id"], reason)
        fields_skipped.append(
            {
                "field": "vision_summaries",
                "doc_id": entry["doc_id"],
                "reason": reason,
                "hint": "Use a doc_id returned by get_vision_document for THIS product.",
            }
        )
    if landed:
        fields_written.append("vision_summaries")


async def _write_consolidated_vision(
    payload: dict,
    tenant_key: str,
    product_id: str,
    db_manager: DatabaseManager | None,
    test_session: AsyncSession | None,
    fields_written: list[str],
    *,
    force: bool,
) -> None:
    """Persist agent-supplied aggregate consolidated_vision via ProductService."""
    from giljo_mcp.services.product_service import ProductService

    product_service = ProductService(
        db_manager=db_manager,
        tenant_key=tenant_key,
        test_session=test_session,
    )
    light = payload["light"]
    medium = payload["medium"]
    await product_service.update_product(
        product_id,
        force=force,
        consolidated_vision_light=light,
        consolidated_vision_light_tokens=len(light.split()),
        consolidated_vision_medium=medium,
        consolidated_vision_medium_tokens=len(medium.split()),
    )
    fields_written.append("consolidated_vision")
