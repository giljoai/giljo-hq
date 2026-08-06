# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductVisionService - Vision document lifecycle management

Handover 0950i: Extracted from ProductService to reduce god-class size.
Per-doc and aggregate summaries are written by the AI agent through the
``update_product_context`` MCP tool; this service does not generate summary
text server-side.

Responsibilities:
- Vision document upload and storage
- Auto-chunking of large documents
- Auto-consolidation (aggregate-hash bookkeeping only post-BE-5117)
- Vision-analysis-completion flag evaluation

Design Principles:
- Single Responsibility: Only vision document lifecycle
- Dependency Injection: Accepts DatabaseManager and tenant_key
- Async/Await: Full SQLAlchemy 2.0 async support
- ProductVisionService may call ProductService to fetch parent Product
- ProductService must NOT import from this module
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.soft_delete import RECOVER_WINDOW_DAYS, recover_window_expired
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    BaseGiljoError,
    ContextError,
    GiljoFileNotFoundError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Product
from giljo_mcp.repositories.vision_document_repository import VisionDocumentRepository
from giljo_mcp.schemas.service_responses import VisionUploadResult
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.tools.chunking import VISION_MAX_INGEST_TOKENS
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProductVisionService:
    """
    Service for managing vision document lifecycle.

    Handles uploading, summarizing, chunking, and consolidating
    vision documents for products.

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        test_session: AsyncSession | None = None,
    ):
        """
        Initialize ProductVisionService.

        Args:
            db_manager: Database manager for async database operations
            tenant_key: Tenant key for multi-tenant isolation
            test_session: Optional AsyncSession for tests to share the same transaction
        """
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._vision_repo = VisionDocumentRepository(db_manager=db_manager)
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def upload_vision_document(
        self,
        product_id: str,
        content: str,
        filename: str,
        auto_chunk: bool = True,
        max_tokens: int = VISION_MAX_INGEST_TOKENS,
    ) -> VisionUploadResult:
        """
        Upload and optionally chunk vision document for product.

        Uses VisionDocumentChunker for intelligent chunking at semantic boundaries.
        Documents exceeding max_tokens are automatically split into chunks.

        Args:
            product_id: Product UUID
            content: Document content (text/markdown)
            filename: Document filename
            auto_chunk: Auto-chunk if content exceeds max_tokens (default: True)
            max_tokens: Max tokens per chunk (default: 25000 for 32K models)

        Returns:
            VisionUploadResult Pydantic model with document_id, document_name,
            chunks_created, and total_tokens

        Raises:
            ValidationError: If validation fails
            ResourceNotFoundError: If product not found
            BaseGiljoError: If upload fails

        Example:
            >>> result = await service.upload_vision_document(
            ...     product_id="abc-123",
            ...     content="# Vision\\n...",
            ...     filename="vision.md"
            ... )
            >>> print(f"Created {result.chunks_created} chunks")
        """
        try:
            async with self._get_session() as session:
                # Verify product exists and belongs to tenant
                product = await self._vision_repo.get_product_by_id(session, product_id, self.tenant_key)

                if not product:
                    raise ResourceNotFoundError(
                        message=f"Product {product_id} not found or access denied",
                        context={"product_id": product_id, "tenant_key": self.tenant_key},
                    )

                # Calculate file size
                file_size = len(content.encode("utf-8"))

                # Create document (inline storage)
                doc = await self._vision_repo.create(
                    session=session,
                    tenant_key=self.tenant_key,
                    product_id=product_id,
                    document_name=filename,
                    content=content,
                    document_type="vision",
                    storage_type="inline",
                    file_size=file_size,
                    is_active=True,
                    display_order=0,
                )

                await session.commit()

                self._logger.info(f"Created vision document {sanitize(doc.id)} for product {sanitize(product_id)}")

                # Per-doc summaries are written by the AI agent via
                # update_product_context. Documents are uploaded with
                # is_summarized=False; the flag flips once the agent
                # persists summary_light + summary_medium.
                total_tokens = len(content) // 4  # Rough estimate: 1 token ~ 4 chars

                # Auto-chunk if enabled
                chunks_created, total_tokens = await self._chunk_document(
                    session, doc, content, auto_chunk, max_tokens, total_tokens
                )

                # Handover 0493: Auto-consolidation after upload
                await self._consolidate_vision(session, product_id)

                return VisionUploadResult(
                    document_id=str(doc.id),
                    document_name=doc.document_name,
                    chunks_created=chunks_created,
                    total_tokens=total_tokens,
                )

        except ValueError as e:
            self._logger.exception("Validation error uploading vision document")
            raise ValidationError(
                message=f"Validation error uploading vision document: {e!s}",
                context={"product_id": product_id, "filename": filename},
            ) from e
        except ResourceNotFoundError:
            raise
        except IntegrityError as e:
            # TSK-9205: two concurrent same-name uploads race past any pre-check
            # SELECT; the loser hits the uq_vision_doc_product_name partial unique
            # index on commit. Map that write-race to the already-exists domain
            # rejection (409) instead of letting it fall into the broad catch and
            # surface as an unhelpful 500. (The session was rolled back when the
            # `async with self._get_session()` context exited with the error.)
            self._logger.info("Duplicate vision document name race for product %s", sanitize(product_id))
            raise AlreadyExistsError(
                message=f"A vision document named '{filename}' already exists for this product.",
                context={"product_id": product_id, "filename": filename, "tenant_key": self.tenant_key},
            ) from e
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to upload vision document")
            raise BaseGiljoError(
                message=f"Failed to upload vision document: {e!s}",
                context={"product_id": product_id, "filename": filename, "tenant_key": self.tenant_key},
            ) from e

    async def _chunk_document(
        self, session, doc, content: str, auto_chunk: bool, max_tokens: int, total_tokens: int
    ) -> tuple[int, int]:
        """Auto-chunk a vision document if enabled.

        Args:
            session: Database session
            doc: VisionDocument ORM instance
            content: Document text content
            auto_chunk: Whether auto-chunking is enabled
            max_tokens: Max tokens per chunk
            total_tokens: Current token estimate

        Returns:
            Tuple of (chunks_created, total_tokens)
        """
        chunks_created = 0

        if not auto_chunk:
            return chunks_created, total_tokens

        from giljo_mcp.context_management.chunker import VisionDocumentChunker

        chunker = VisionDocumentChunker(target_chunk_size=max_tokens)

        try:
            chunk_result = await chunker.chunk_vision_document(
                session=session, tenant_key=self.tenant_key, vision_document_id=str(doc.id)
            )

            await session.commit()

            chunks_created = chunk_result["chunks_created"]
            total_tokens = chunk_result["total_tokens"]

            self._logger.info(f"Chunked document {doc.id}: {chunks_created} chunks, {total_tokens} tokens")
        except (ContextError, GiljoFileNotFoundError, OSError) as e:
            self._logger.warning(f"Document {doc.id} created but chunking failed: {e}")

        return chunks_created, total_tokens

    async def evaluate_vision_analysis_complete(
        self,
        session: AsyncSession,
        product_id: str,
    ) -> bool:
        """Recompute Product.vision_analysis_complete (BE-5117).

        TRUE iff every active VisionDocument for this product has BOTH
        summary_light AND summary_medium populated AND the product has BOTH
        consolidated_vision_light AND consolidated_vision_medium populated.

        Called atomically inside the update_product_context tool transaction.

        Args:
            session: Active database session (caller manages commit)
            product_id: Product UUID

        Returns:
            The computed flag value (also persisted on the product row).
        """
        complete, _missing = await self.evaluate_vision_completion(session, product_id)
        return complete

    async def evaluate_vision_completion(
        self,
        session: AsyncSession,
        product_id: str,
    ) -> tuple[bool, list[str]]:
        """Recompute the completion flag AND report what is still outstanding.

        FE-9320: staged writes need the caller to be TOLD the completion state
        rather than infer it. Same computation as
        :meth:`evaluate_vision_analysis_complete` (which delegates here), plus a
        list of agent-readable reasons the analysis is not complete yet. The list
        is empty exactly when the flag is True.
        """
        # BE-6210: force-refresh the product AND its vision_documents collection.
        # The per-doc summaries and the aggregate consolidated_vision are written
        # through *separate* sessions (VisionDocumentRepository / ProductService on
        # db_manager), then this evaluator runs on the tool's outer session. Without
        # populate_existing the identity-mapped Product/vision_documents are returned
        # with their pre-write attribute snapshot, so the flag is computed against
        # stale data and committed as a false "Pending analysis" despite the data
        # being complete. populate_existing overwrites the cached attributes; under
        # Postgres READ COMMITTED the freshly committed rows are visible.
        stmt = (
            select(Product)
            .where(Product.id == product_id, Product.tenant_key == self.tenant_key)
            .options(selectinload(Product.vision_documents))
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is None:
            raise ResourceNotFoundError(
                message="Product not found",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            )

        # BE-6130b: exclude trashed docs (the relationship loads soft-deleted rows).
        active_docs = [doc for doc in product.vision_documents if doc.is_active and doc.deleted_at is None]
        all_docs_summarized = bool(active_docs) and all(doc.summary_light and doc.summary_medium for doc in active_docs)
        aggregate_populated = bool(product.consolidated_vision_light and product.consolidated_vision_medium)

        new_value = all_docs_summarized and aggregate_populated
        product.vision_analysis_complete = new_value
        await session.flush()

        missing: list[str] = []
        if not active_docs:
            missing.append("at least one active vision document (upload one, or call create_vision_document)")
        missing.extend(
            f"vision_summaries entry with both light and medium for doc_id {doc.id} ({doc.document_name})"
            for doc in active_docs
            if not (doc.summary_light and doc.summary_medium)
        )
        if not aggregate_populated:
            missing.append("consolidated_vision with both light and medium")
        return new_value, missing

    async def _consolidate_vision(self, session, product_id: str) -> None:
        """Auto-consolidate vision documents after upload.

        Handover 0493: Ensures light/medium summaries are always available.

        Args:
            session: Database session
            product_id: Product UUID
        """
        try:
            from giljo_mcp.services.consolidation_service import ConsolidatedVisionService

            consolidation_service = ConsolidatedVisionService()
            await consolidation_service.consolidate_vision_documents(
                product_id=product_id,
                session=session,
                tenant_key=self.tenant_key,
                force=True,
            )
            self._logger.info(f"Auto-consolidated vision documents for product {sanitize(product_id)}")
        except (ValidationError, ResourceNotFoundError, ValueError, KeyError) as e:
            self._logger.warning(f"Auto-consolidation failed for product {sanitize(product_id)}: {sanitize(e)}")

    # ---- BE-5022b: Service wrappers for VisionDocumentRepository methods ----

    async def create_document(
        self,
        session: AsyncSession,
        product_id: str,
        document_name: str,
        content: str,
        document_type: str = "vision",
        storage_type: str = "inline",
        file_path: str | None = None,
        file_size: int | None = None,
        display_order: int = 0,
        version: str = "1.0.0",
    ) -> Any:
        """Create a new vision document.

        BE-5022b: Service wrapper for VisionDocumentRepository.create().

        Args:
            session: Active database session
            product_id: Product UUID
            document_name: Human-readable name
            content: Document content
            document_type: Document category
            storage_type: How content is stored
            file_path: Optional file path
            file_size: Optional file size in bytes
            display_order: Display order in UI
            version: Semantic version

        Returns:
            Created VisionDocument instance
        """
        repo = self._vision_repo
        return await repo.create(
            session=session,
            tenant_key=self.tenant_key,
            product_id=product_id,
            document_name=document_name,
            content=content,
            document_type=document_type,
            storage_type=storage_type,
            file_path=file_path,
            file_size=file_size,
            display_order=display_order,
            version=version,
        )

    async def get_document_by_id(
        self,
        session: AsyncSession,
        document_id: str,
    ) -> Any:
        """Get a vision document by ID.

        BE-5022b: Service wrapper for VisionDocumentRepository.get_by_id().

        Args:
            session: Active database session
            document_id: Vision document UUID

        Returns:
            VisionDocument instance or None
        """
        repo = self._vision_repo
        return await repo.get_by_id(session, self.tenant_key, document_id)

    async def list_documents_by_product(
        self,
        session: AsyncSession,
        product_id: str,
        active_only: bool = True,
    ) -> list:
        """List vision documents for a product.

        BE-5022b: Service wrapper for VisionDocumentRepository.list_by_product().

        Args:
            session: Active database session
            product_id: Product UUID
            active_only: Only return active documents

        Returns:
            List of VisionDocument instances
        """
        repo = self._vision_repo
        return await repo.list_by_product(
            session=session,
            tenant_key=self.tenant_key,
            product_id=product_id,
            active_only=active_only,
        )

    async def update_document_content(
        self,
        session: AsyncSession,
        document_id: str,
        new_content: str,
    ) -> Any:
        """Update vision document content.

        BE-5022b: Service wrapper for VisionDocumentRepository.update_content().

        Args:
            session: Active database session
            document_id: Vision document UUID
            new_content: New document content

        Returns:
            Updated VisionDocument instance or None
        """
        repo = self._vision_repo
        return await repo.update_content(
            session=session,
            tenant_key=self.tenant_key,
            document_id=document_id,
            new_content=new_content,
        )

    async def delete_document(
        self,
        session: AsyncSession,
        document_id: str,
    ) -> dict:
        """Soft-delete a vision document (BE-6130b trash action).

        Stamps ``deleted_at`` so the doc + its RAG chunks go dormant together;
        ``restore_document`` recovers them as one unit. (Was a hard delete;
        the hard path stays as ``VisionDocumentRepository.delete`` for purge.)

        Args:
            session: Active database session
            document_id: Vision document UUID

        Returns:
            Dict with deletion result
        """
        repo = self._vision_repo
        return await repo.soft_delete(
            session=session,
            tenant_key=self.tenant_key,
            document_id=document_id,
        )

    async def restore_document(
        self,
        session: AsyncSession,
        document_id: str,
    ) -> Any:
        """Restore a soft-deleted vision document (and re-surface its chunks).

        BE-6130b: Service wrapper for VisionDocumentRepository.restore().

        Args:
            session: Active database session
            document_id: Vision document UUID

        Returns:
            The restored VisionDocument instance
        """
        repo = self._vision_repo
        trashed = await repo.get_deleted_by_id(session, self.tenant_key, document_id)
        if trashed is None:
            raise ResourceNotFoundError("Deleted document not found")
        # BE-6130b decision A: recovery is gated by the 30-day window at this boundary.
        if recover_window_expired(trashed.deleted_at):
            raise ValidationError(
                f"This vision document was deleted more than {RECOVER_WINDOW_DAYS} days ago "
                "and can no longer be recovered.",
                context={"operation": "vision.restore", "document_id": document_id},
            )
        return await repo.restore(
            session=session,
            tenant_key=self.tenant_key,
            document_id=document_id,
        )

    async def list_deleted_documents(
        self,
        session: AsyncSession,
        product_id: str | None = None,
    ) -> list:
        """List soft-deleted vision documents for the recover dialog.

        BE-6130b: Service wrapper for VisionDocumentRepository.list_deleted().

        Args:
            session: Active database session
            product_id: Optional product scope

        Returns:
            List of soft-deleted VisionDocument instances
        """
        repo = self._vision_repo
        return await repo.list_deleted(
            session=session,
            tenant_key=self.tenant_key,
            product_id=product_id,
        )

    async def purge_expired_deleted_documents(self) -> int:
        """Hard-delete trashed vision docs past the recovery window (TSK-6132 reaper).

        Walks this tenant's soft-deleted vision documents and permanently removes
        those whose ``deleted_at`` is past ``RECOVER_WINDOW_DAYS`` (the same
        boundary ``restore_document`` refuses to recover past). The doc's RAG
        chunks cascade at the DB level. Returns the count purged; tenant-isolated
        and idempotent (re-running finds none). Opens its own session so it can be
        driven directly by the startup reaper.
        """
        purged = 0
        async with self._get_session() as session:
            for doc in await self._vision_repo.list_deleted(session, self.tenant_key):
                if not recover_window_expired(doc.deleted_at):
                    continue
                try:
                    if await self._vision_repo.hard_delete_trashed(session, self.tenant_key, doc.id):
                        purged += 1
                except Exception:
                    self._logger.exception("Reaper failed to purge vision document %s", doc.id)
        return purged
