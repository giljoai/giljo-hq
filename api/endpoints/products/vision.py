# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

# ruff: noqa: B904, UP006, PERF401
"""
Product Vision Document Endpoints - Handover 0503

Handles vision document upload and retrieval operations using ProductService.

Handover 0503: Consolidated vision endpoints, updated paths, added proper response schemas.
Handover 0126: Initial implementation with direct database access.
Handover 0731d: Updated for typed ProductService returns (VisionUploadResult instead of dict).
SEC-0001 Phase 2: Upload guardrails (size cap, extension allowlist, filename
    sanitization, strict UTF-8 + byte-sniff, structured error codes).
"""

import logging
from typing import List  # noqa: UP035

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_tenant_key
from api.schemas.vision_document import VisionDocumentResponse
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.config_manager import get_config
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import User
from giljo_mcp.security.upload_guard import (
    UploadContentError,
    UploadFilenameError,
    enforce_text_content,
    sanitize_upload_filename,
)
from giljo_mcp.services.product_vision_service import ProductVisionService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_product_vision_service
from .models import VisionChunk


logger = logging.getLogger(__name__)
router = APIRouter()


def _raise_too_large(max_bytes: int) -> None:
    """Raise the shared structured 413 for oversize uploads (SEC-0001)."""
    raise HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail={
            "error_code": "UPLOAD_TOO_LARGE",
            "message": f"File is too large. Maximum size is {max_bytes // 1024 // 1024} MB.",
            "max_bytes": max_bytes,
        },
    )


async def _read_upload_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Stream the upload body, aborting if it exceeds ``max_bytes``.

    FastAPI's ``UploadFile`` does not cap size on its own, so we read in
    64 KB chunks and track a running total. Used by both upload endpoints
    as the Layer-2 size guard.
    """
    chunks: list[bytes] = []
    total = 0
    chunk_size = 65536
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            _raise_too_large(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/{product_id}/vision", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_vision_document(
    product_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_product_vision_service),
) -> dict:
    """
    Upload vision document for product with automatic chunking.

    Accepts .txt/.md/.markdown files up to the configured upload cap
    (``UploadConfig.max_upload_bytes`` -- 5 MB default, SEC-0001). Documents
    are automatically chunked at 25K tokens using semantic boundaries
    (headers, paragraphs).

    Handover 0503: Updated path from /upload-vision to /vision (canonical endpoint).
    Handover 0500: Implemented vision upload with intelligent chunking.
    SEC-0001 Phase 2: Extension allowlist + filename sanitization + byte-sniff
        + strict UTF-8 + two-layer size cap + structured error codes.
    """
    upload_cfg = get_config().upload
    max_bytes = upload_cfg.max_upload_bytes

    # Layer 1 size guard: Content-Length pre-check (fast reject before body read).
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        _raise_too_large(max_bytes)

    # Filename sanitization (raw attacker input -- convert to 400 on failure).
    try:
        safe_filename = sanitize_upload_filename(file.filename)
    except UploadFilenameError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "UPLOAD_FILENAME_INVALID",
                "message": "Filename contains invalid characters or is too long.",
                "reason": str(exc),
            },
        )

    logger.info(
        "User %s uploading vision document '%s' for product %s",
        sanitize(current_user.username),
        sanitize(safe_filename),
        sanitize(product_id),
    )

    # Extension allowlist -- 415 (type not supported), not 400.
    ext_lower = safe_filename.lower()
    if not any(ext_lower.endswith(ext) for ext in upload_cfg.allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error_code": "UPLOAD_TYPE_NOT_ALLOWED",
                "message": "Only .txt and .md files are accepted.",
                "allowed_extensions": list(upload_cfg.allowed_extensions),
            },
        )

    # Layer 2 size guard: streaming read with running byte counter.
    content = await _read_upload_capped(file, max_bytes)

    # Byte-sniff: reject binary payloads that spoof a .txt/.md extension.
    try:
        enforce_text_content(content, sniff_bytes=upload_cfg.sniff_bytes)
    except UploadContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error_code": "UPLOAD_CONTENT_NOT_TEXT",
                "message": "File does not look like plain text. Please upload a .txt or .md file.",
                "reason": str(exc),
            },
        )

    # Strict UTF-8 decode. ``enforce_text_content`` already verified decode
    # succeeds; the defensive try/except converts any pathological race into
    # the same structured 415.
    try:
        content_str = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error_code": "UPLOAD_CONTENT_NOT_TEXT",
                "message": "File must be valid UTF-8 encoded text.",
            },
        )

    try:
        # Upload via ProductVisionService (Handover 0950i: extracted from ProductService)
        # Handover 0731d: returns VisionUploadResult Pydantic model
        result = await vision_service.upload_vision_document(
            product_id=product_id,
            content=content_str,
            filename=safe_filename,
            auto_chunk=True,
            max_tokens=25000,
        )

        logger.info(
            "Successfully uploaded vision document %s: %d chunks, %d tokens",
            result.document_id,
            result.chunks_created,
            result.total_tokens,
        )

        # BE-5118: a freshly-uploaded doc has no summaries yet, so the
        # product-level gating flag must drop back to FALSE. The evaluator
        # handles the general case (TRUE iff every active doc + aggregate
        # has light + medium summaries) and is idempotent — safe to call
        # from any write boundary that mutates the doc set.
        try:
            await vision_service.evaluate_vision_analysis_complete(db, product_id)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to re-evaluate vision_analysis_complete after upload for product %s",
                sanitize(product_id),
            )

        return {
            "success": True,
            "message": "Vision document uploaded and chunked successfully",
            "document_id": result.document_id,
            "document_name": result.document_name,
            "chunks_created": result.chunks_created,
            "total_tokens": result.total_tokens,
        }

    except ValueError as e:
        # Handover 0508: Catch validation errors from ProductService
        error_msg = str(e).lower()
        if "already exists" in error_msg or "duplicate" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A vision document named '{safe_filename}' already exists for this product. Please rename your file and try again.",
            )
        logger.warning("Vision upload validation error: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload request.")
    except (ResourceNotFoundError, ValidationError, AuthorizationError, AlreadyExistsError, HTTPException):
        # TSK-9205: the service now raises AlreadyExistsError (409) on a duplicate
        # -name write race; let the global handler map it to 409 rather than the
        # broad catch below turning it into a 500.
        raise
    except Exception as e:  # Broad catch: API boundary, converts to HTTP error
        logger.exception("Vision upload failed")
        # Handover 0508: Check for IntegrityError (duplicate constraint violation)
        error_str = str(e).lower()
        if "unique" in error_str or "duplicate" in error_str or "uq_vision_doc" in error_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A vision document named '{safe_filename}' already exists for this product. Please rename your file and try again.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed. Please try again or contact support.",
        )


@router.get("/{product_id}/vision", response_model=List[VisionDocumentResponse])
async def list_vision_documents(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    tenant_key: str = Depends(get_tenant_key),
) -> List[VisionDocumentResponse]:
    """
    List all vision documents for a product.

    Returns complete vision document records with metadata.

    Handover 0503: Added GET endpoint for listing vision documents.
    """
    from sqlalchemy import and_, select

    from giljo_mcp.models import VisionDocument

    logger.debug(
        "User %s listing vision documents for product %s", sanitize(current_user.username), sanitize(product_id)
    )

    # Query vision documents for this product. deleted_at IS NULL is the same
    # trashed-parent exclusion the chunks reader below needs, and the sibling
    # router api/endpoints/vision_documents.py already applies it alongside a
    # dedicated /deleted trash view -- so a trashed doc surfacing in the main
    # list here contradicted the product's own model of what "trash" means.
    stmt = (
        select(VisionDocument)
        .where(
            and_(
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.product_id == product_id,
                VisionDocument.deleted_at.is_(None),
            )
        )
        .order_by(VisionDocument.display_order, VisionDocument.created_at)
    )

    result = await db.execute(stmt)
    documents = result.scalars().all()

    # Convert to response models
    response_docs = []
    for doc in documents:
        # Check if summaries exist
        has_summaries = bool(doc.summary_light or doc.summary_medium)

        response_docs.append(
            VisionDocumentResponse(
                id=doc.id,
                tenant_key=doc.tenant_key,
                product_id=doc.product_id,
                document_name=doc.document_name,
                document_type=doc.document_type,
                storage_type=doc.storage_type,
                vision_path=doc.vision_path,
                vision_document=doc.vision_document,
                chunked=doc.chunked,
                chunk_count=doc.chunk_count,
                total_tokens=doc.total_tokens,
                file_size=doc.file_size,
                content_hash=doc.content_hash,
                version=doc.version,
                is_active=doc.is_active,
                display_order=doc.display_order,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                chunked_at=None,  # VisionDocument model does not have chunked_at field
                meta_data=doc.meta_data or {},
                # Summary fields (Handover 0246b: light/medium only)
                summary_light=doc.summary_light,
                summary_medium=doc.summary_medium,
                summary_light_tokens=doc.summary_light_tokens,
                summary_medium_tokens=doc.summary_medium_tokens,
                has_summaries=has_summaries,
            )
        )

    logger.debug("Retrieved %d vision documents for product %s", len(response_docs), sanitize(product_id))

    return response_docs


@router.delete("/{product_id}/vision/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vision_document(
    product_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_product_vision_service),
):
    """
    Delete a vision document by ID.

    Removes the vision document and its associated chunks (CASCADE).

    Handover 0503: Added DELETE endpoint for vision documents.
    """
    from sqlalchemy import and_, delete, select

    from giljo_mcp.models import MCPContextIndex, VisionDocument

    logger.info(
        "User %s deleting vision document %s for product %s",
        sanitize(current_user.username),
        sanitize(doc_id),
        sanitize(product_id),
    )

    # Verify document exists and belongs to this product/tenant
    stmt = select(VisionDocument).where(
        and_(
            VisionDocument.id == doc_id,
            VisionDocument.product_id == product_id,
            VisionDocument.tenant_key == tenant_key,
        )
    )

    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vision document not found")

    # Delete associated chunks first
    delete_chunks_stmt = delete(MCPContextIndex).where(
        and_(
            MCPContextIndex.vision_document_id == doc_id,
            MCPContextIndex.tenant_key == tenant_key,
        )
    )
    await db.execute(delete_chunks_stmt)

    # Delete the vision document
    await db.delete(doc)
    await db.commit()

    # BE-5118: remaining doc set may now satisfy the gate (e.g. the deleted
    # doc was the only unsummarized one). Re-evaluate so the flag reflects
    # post-delete reality.
    try:
        await vision_service.evaluate_vision_analysis_complete(db, product_id)
        await db.commit()
    except Exception:
        logger.exception(
            "Failed to re-evaluate vision_analysis_complete after delete for product %s",
            sanitize(product_id),
        )

    logger.info("Successfully deleted vision document %s", sanitize(doc_id))


@router.get("/{product_id}/vision-chunks", response_model=List[VisionChunk])
async def get_vision_chunks(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    tenant_key: str = Depends(get_tenant_key),
) -> List[VisionChunk]:
    """
    Get vision document chunks for product (legacy endpoint).

    Returns all context chunks associated with product's vision documents.
    Chunks are ordered by vision_document_id and chunk_order.

    Note: Consider using GET /{product_id}/vision instead for full document metadata.

    Handover 0500: Implemented vision chunks retrieval.
    """
    from sqlalchemy import and_, select

    from giljo_mcp.models import MCPContextIndex, VisionDocument

    logger.debug(
        "User %s retrieving vision chunks for product %s", sanitize(current_user.username), sanitize(product_id)
    )

    # Query context chunks for this product.
    #
    # The join to VisionDocument is load-bearing, not decoration. Soft-delete
    # stamps deleted_at and deliberately LEAVES the chunks intact so a restore
    # brings the document and its chunks back as one unit, so filtering on the
    # junction columns alone kept serving a trashed document's full text.
    # VisionDocumentRepository.soft_delete states the contract in its own
    # docstring -- "chunk retrieval excludes chunks of a trashed parent" -- and
    # the sibling reader ContextRepository.search_chunks already honours it.
    # Matching that sibling exactly: trashed parents only, since it is the
    # reader doing the identical job.
    stmt = (
        select(MCPContextIndex)
        .join(VisionDocument, VisionDocument.id == MCPContextIndex.vision_document_id)
        .where(
            and_(
                MCPContextIndex.tenant_key == tenant_key,
                MCPContextIndex.product_id == product_id,
                MCPContextIndex.vision_document_id.isnot(None),
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.deleted_at.is_(None),
            )
        )
        .order_by(MCPContextIndex.vision_document_id, MCPContextIndex.chunk_order)
    )

    result = await db.execute(stmt)
    chunks = result.scalars().all()

    # Convert to response model
    response_chunks = []
    for chunk in chunks:
        response_chunks.append(
            VisionChunk(
                chunk_number=chunk.chunk_order,
                total_chunks=len(chunks),
                content=chunk.content,
                char_start=0,  # Not tracked in current schema
                char_end=len(chunk.content),
                boundary_type="semantic",  # Default boundary type
                keywords=chunk.keywords or [],
                headers=chunk.summary.split("\n") if chunk.summary else [],
            )
        )

    logger.debug("Retrieved %d vision chunks for product %s", len(response_chunks), sanitize(product_id))

    return response_chunks
