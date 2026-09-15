# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_tenant_key
from api.schemas.vision_document import (
    DeleteResponse,
    VisionDocumentResponse,
)
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.config_manager import get_config
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product, User
from giljo_mcp.security.upload_guard import (
    UploadContentError,
    UploadFilenameError,
    enforce_text_content,
    sanitize_upload_filename,
)
from giljo_mcp.services.consolidation_service import ConsolidatedVisionService
from giljo_mcp.services.product_vision_service import ProductVisionService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vision Documents"])


async def trigger_consolidation(product_id: str, tenant_key: str, db_session: AsyncSession) -> None:
    try:
        consolidation_service = ConsolidatedVisionService()
        result = await consolidation_service.consolidate_vision_documents(
            product_id=product_id, session=db_session, tenant_key=tenant_key, force=False
        )

        logger.info(
            f"vision_documents_consolidated: product_id={sanitize(product_id)}, "
            f"light_tokens={result.light.tokens}, medium_tokens={result.medium.tokens}"
        )
    except ValidationError as e:
        logger.debug(f"consolidation_skipped: product_id={sanitize(product_id)}, reason={sanitize(e.error_code)}")
    except (SQLAlchemyError, ValueError, KeyError, ResourceNotFoundError):
        logger.exception(f"consolidation_failed: product_id={sanitize(product_id)}")


async def get_db():
    from api.app_state import state

    if not state.db_manager:
        raise RuntimeError("Database manager not initialized")

    async with state.db_manager.get_session_async() as session:
        yield session


def get_vision_service(tenant_key: str = Depends(get_tenant_key)):
    from api.app_state import state

    if not state.db_manager:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not available")

    return ProductVisionService(
        db_manager=state.db_manager,
        tenant_key=tenant_key,
    )


def _raise_upload_too_large(max_bytes: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail={
            "error_code": "UPLOAD_TOO_LARGE",
            "message": f"File is too large. Maximum size is {max_bytes // 1024 // 1024} MB.",
            "max_bytes": max_bytes,
        },
    )


async def _read_upload_capped(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    chunk_size = 65536
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            _raise_upload_too_large(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/", response_model=VisionDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_vision_document(
    request: Request,
    product_id: str = Form(...),
    document_name: str = Form(...),
    document_type: str = Form("vision"),
    content: str | None = Form(None),
    vision_file: UploadFile | None = File(None),
    display_order: int = Form(0),
    version: str = Form("1.0.0"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """
    Create a new vision document for a product.

    **Storage** (BE-5115: inline-only): Complete document stored in
    `vision_document` TEXT column. Uploaded files are decoded to UTF-8 text
    and persisted inline; nothing is written to disk. `storage_type` is
    always `'inline'`, `vision_path` is always `NULL`.

    **Summarization**: Large documents (>5K tokens) automatically generate:
    - Light summary (33% of original)
    - Medium summary (66% of original)

    **Input Options** (mutually compatible):
    - **File Upload**: Provide `vision_file` (decoded to text, stored inline)
    - **Inline Content**: Provide `content` (stored inline)

    Args:
        product_id: Product ID this document belongs to
        document_name: User-friendly document name
        document_type: Document category (vision, architecture, features, etc.)
        content: Inline document content (optional)
        vision_file: Uploaded file (optional)
        display_order: Display order in UI (default: 0)
        version: Semantic version (default: "1.0.0")

    Returns:
        VisionDocumentResponse: Created vision document

    Raises:
        HTTPException 400: If neither content nor file provided
        HTTPException 404: If product not found
        HTTPException 500: If creation or summarization fails
    """
    try:
        result = await db.execute(select(Product).filter(Product.id == product_id, Product.tenant_key == tenant_key))
        product = result.scalar_one_or_none()

        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {product_id} not found")

        try:
            uuid.UUID(product_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid product ID format.") from None

        document_content = content
        file_size = None

        if vision_file:
            upload_cfg = get_config().upload
            max_bytes = upload_cfg.max_upload_bytes

            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                _raise_upload_too_large(max_bytes)

            try:
                safe_filename = sanitize_upload_filename(vision_file.filename)
            except UploadFilenameError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": "UPLOAD_FILENAME_INVALID",
                        "message": "Filename contains invalid characters or is too long.",
                        "reason": str(exc),
                    },
                ) from exc

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

            content_bytes = await _read_upload_capped(vision_file, max_bytes)

            try:
                enforce_text_content(content_bytes, sniff_bytes=upload_cfg.sniff_bytes)
            except UploadContentError as exc:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail={
                        "error_code": "UPLOAD_CONTENT_NOT_TEXT",
                        "message": "File does not look like plain text. Please upload a .txt or .md file.",
                        "reason": str(exc),
                    },
                ) from exc

            try:
                document_content = content_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail={
                        "error_code": "UPLOAD_CONTENT_NOT_TEXT",
                        "message": "File must be valid UTF-8 encoded text.",
                    },
                ) from exc

            file_size = len(content_bytes)
        elif content:
            file_size = len(content.encode("utf-8"))

        if not document_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No content provided. Provide either 'content' or 'vision_file'.",
            )

        doc = await vision_service.create_document(
            session=db,
            product_id=product_id,
            document_name=document_name,
            content=document_content,
            document_type=document_type,
            storage_type="inline",
            file_path=None,
            file_size=file_size,
            display_order=display_order,
            version=version,
        )
        await db.commit()

        total_tokens = len(document_content) // 4

        if total_tokens > 25000:
            try:
                from giljo_mcp.context_management.chunker import VisionDocumentChunker

                logger.info("Chunking document %s: %d tokens exceeds 25K threshold", doc.id, total_tokens)

                chunker = VisionDocumentChunker(target_chunk_size=25000)
                chunk_result = await chunker.chunk_vision_document(
                    session=db, tenant_key=tenant_key, vision_document_id=str(doc.id)
                )
                await db.commit()

                if chunk_result.get("success"):
                    logger.info(
                        "Chunked document %s: %d chunks, %d tokens",
                        doc.id,
                        chunk_result.get("chunks_created", 0),
                        chunk_result.get("total_tokens", 0),
                    )
                else:
                    logger.warning(
                        "Document %s created but chunking failed: %s", doc.id, sanitize(str(chunk_result.get("error")))
                    )
            except (ImportError, SQLAlchemyError, ValueError) as e:
                logger.warning(f"Document {doc.id} created but chunking failed: {e}")

        await trigger_consolidation(product_id, tenant_key, db)

        await db.refresh(doc)

        return VisionDocumentResponse.model_validate(doc)

    except HTTPException:
        await db.rollback()
        raise
    except (SQLAlchemyError, OSError, UnicodeDecodeError, ValueError) as e:
        await db.rollback()
        logger.error("Failed to create vision document: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create vision document. Check server logs.",
        ) from e


@router.get("/{document_id}", response_model=VisionDocumentResponse)
async def get_vision_document(
    document_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """
    Get a single vision document by ID.

    **Handover 0246b**: Returns full document including vision_document content.
    Used for "Full" preview in product details dialog.

    **Multi-Tenant Isolation**: Only returns document if it belongs to the authenticated tenant.

    Args:
        document_id: Vision document ID

    Returns:
        VisionDocumentResponse with full content

    Raises:
        404: Document not found or belongs to different tenant
    """
    from giljo_mcp.models import VisionDocument

    result = await db.execute(
        select(VisionDocument).where(
            VisionDocument.id == document_id,
            VisionDocument.tenant_key == tenant_key,
            VisionDocument.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vision document {document_id} not found")

    return VisionDocumentResponse.model_validate(doc)


@router.get("/product/{product_id}", response_model=list[VisionDocumentResponse])
async def list_vision_documents(
    product_id: str,
    active_only: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """
    List all vision documents for a product.

    **Multi-Tenant Isolation**: Only returns documents for the authenticated tenant.

    **Filtering**:
    - `active_only=True` (default): Returns only active documents
    - `active_only=False`: Returns all documents including inactive/archived

    **Ordering**: Results ordered by display_order ASC, created_at ASC

    Args:
        product_id: Product ID to list documents for
        active_only: If True, only return active documents (default: True)

    Returns:
        List[VisionDocumentResponse]: List of vision documents

    Raises:
        HTTPException 500: If listing fails
    """
    docs = await vision_service.list_documents_by_product(session=db, product_id=product_id, active_only=active_only)
    return [VisionDocumentResponse.model_validate(doc) for doc in docs]


@router.put("/{document_id}", response_model=VisionDocumentResponse)
async def update_vision_document(
    document_id: str,
    content: str = Form(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """
    Update vision document content.

    **Automatic Updates**:
    - Recalculates content hash (SHA-256)
    - Updates updated_at timestamp
    - Regenerates summaries for large documents (>5K tokens)

    Args:
        document_id: Document ID to update
        content: New document content

    Returns:
        VisionDocumentResponse: Updated vision document

    Raises:
        HTTPException 404: If document not found
        HTTPException 500: If update or summarization fails
    """
    try:
        doc = await vision_service.update_document_content(session=db, document_id=document_id, new_content=content)

        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Vision document {document_id} not found"
            )

        await db.commit()

        await trigger_consolidation(doc.product_id, tenant_key, db)

        await db.refresh(doc)

        return VisionDocumentResponse.model_validate(doc)

    except HTTPException:
        await db.rollback()
        raise
    except (SQLAlchemyError, ValueError) as e:
        await db.rollback()
        logger.error("Failed to update vision document: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update vision document. Check server logs.",
        ) from e


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_vision_document(
    document_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """
    Soft-delete (trash) a vision document.

    **BE-6130b soft-delete**:
    - Stamps ``deleted_at`` so the doc drops out of every live read.
    - Its MCPContextIndex chunks are LEFT INTACT (cascade only fires on a hard
      delete) and excluded from retrieval, so ``POST /{id}/restore`` recovers the
      doc and its chunks as one unit.

    **Multi-Tenant Isolation**: Only allows deletion of documents belonging to tenant.

    Args:
        document_id: Document ID to trash

    Returns:
        DeleteResponse: result with chunks_deleted = chunks that went dormant

    Raises:
        HTTPException 404: If document not found (or already trashed)
        HTTPException 500: If deletion fails
    """
    try:
        from giljo_mcp.models import VisionDocument

        result = await db.execute(
            select(VisionDocument).where(
                VisionDocument.id == document_id,
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.deleted_at.is_(None),
            )
        )
        doc = result.scalar_one_or_none()

        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Vision document {document_id} not found"
            )

        product_id = doc.product_id

        delete_result = await vision_service.delete_document(session=db, document_id=document_id)

        await db.commit()

        await trigger_consolidation(product_id, tenant_key, db)

        return DeleteResponse(**delete_result)

    except HTTPException:
        await db.rollback()
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Failed to delete vision document: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete vision document. Check server logs.",
        ) from e


@router.get("/product/{product_id}/deleted", response_model=list[VisionDocumentResponse])
async def list_deleted_vision_documents(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """List soft-deleted (trashed) vision documents for a product (recover dialog).

    **Multi-Tenant Isolation**: Only returns trashed documents for the tenant.
    Ordered most-recently-trashed first.
    """
    docs = await vision_service.list_deleted_documents(session=db, product_id=product_id)
    return [VisionDocumentResponse.model_validate(doc) for doc in docs]


@router.post("/{document_id}/restore", response_model=VisionDocumentResponse)
async def restore_vision_document(
    document_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
    vision_service: ProductVisionService = Depends(get_vision_service),
):
    """Restore a soft-deleted (trashed) vision document and re-surface its chunks.

    The chunks were never deleted, so retrieval re-includes them the moment the
    parent is live again — the doc + chunks recover as one unit. Re-triggers
    consolidation so the restored content re-enters the aggregate.

    Raises:
        HTTPException 404: If no trashed document matched the id for the tenant
        HTTPException 500: If restore fails
    """
    try:
        doc = await vision_service.restore_document(session=db, document_id=document_id)
        product_id = doc.product_id
        await db.commit()

        await trigger_consolidation(product_id, tenant_key, db)

        await db.refresh(doc)
        return VisionDocumentResponse.model_validate(doc)

    except ResourceNotFoundError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Vision document {document_id} not found"
        ) from e
    except ValidationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message) from e
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("Failed to restore vision document: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restore vision document. Check server logs.",
        ) from e


@router.post("/products/{product_id}/regenerate-consolidated", response_model=dict)
async def regenerate_consolidated_vision(
    product_id: str,
    force: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
):
    """
    Manually regenerate consolidated vision summaries for a product.

    **Handover 0377 Phase 4**: Admin endpoint for forcing regeneration.

    **Use Cases**:
    - Consolidation algorithm changed (want to regenerate with new logic)
    - Manual refresh after bulk vision document updates
    - Testing/debugging consolidation behavior

    **Force Parameter**:
    - `force=False` (default): Only regenerate if content hash changed
    - `force=True`: Always regenerate even if content unchanged

    Args:
        product_id: Product ID to regenerate consolidated vision for
        force: Force regeneration even if no changes detected

    Returns:
        {
            "success": bool,
            "light_tokens": int,
            "medium_tokens": int,
            "source_docs": ["doc_id1", ...],
            "hash": "sha256_hash"
        }

    Raises:
        HTTPException 400: If consolidation fails or skipped
        HTTPException 404: If product not found
    """
    result = await db.execute(select(Product).filter(Product.id == product_id, Product.tenant_key == tenant_key))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {product_id} not found")

    consolidation_service = ConsolidatedVisionService()
    consolidation_result = await consolidation_service.consolidate_vision_documents(
        product_id=product_id, session=db, tenant_key=tenant_key, force=force
    )

    return {
        "success": True,
        "light_tokens": consolidation_result.light.tokens,
        "medium_tokens": consolidation_result.medium.tokens,
        "source_docs": consolidation_result.source_docs,
        "hash": consolidation_result.hash,
    }


@router.get("/{document_id}/ai-summary/{level}")
async def get_ai_summary(
    document_id: str,
    level: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    tenant_key: str = Depends(get_tenant_key),
):
    """
    Get AI summary content for a vision document at a given compression level.

    BE-5117b: Reads directly from VisionDocument.summary_light / summary_medium
    columns; the legacy per-doc summary table was dropped.

    Args:
        document_id: Vision document ID
        level: Compression level ('light' or 'medium')

    Returns:
        Dict with summary text, token count, and level label
    """
    if level not in ("light", "medium"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid level: {level}. Use 'light' or 'medium'."
        )

    from giljo_mcp.models import VisionDocument

    result = await db.execute(
        select(VisionDocument).where(
            VisionDocument.id == document_id,
            VisionDocument.tenant_key == tenant_key,
            VisionDocument.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vision document {document_id} not found")

    summary_text = doc.summary_light if level == "light" else doc.summary_medium
    summary_tokens = doc.summary_light_tokens if level == "light" else doc.summary_medium_tokens

    if not summary_text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No {level} summary found for document {document_id}"
        )

    return {
        "summary": summary_text,
        "tokens": summary_tokens,
        "level": level.capitalize(),
    }
