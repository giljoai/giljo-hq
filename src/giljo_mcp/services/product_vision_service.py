# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._vision_repo = VisionDocumentRepository(db_manager=db_manager)
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def upload_vision_document(
        self,
        product_id: str,
        content: str,
        filename: str,
        auto_chunk: bool = True,
        max_tokens: int = VISION_MAX_INGEST_TOKENS,
    ) -> VisionUploadResult:
        try:
            async with self._get_session() as session:
                product = await self._vision_repo.get_product_by_id(session, product_id, self.tenant_key)

                if not product:
                    raise ResourceNotFoundError(
                        message=f"Product {product_id} not found or access denied",
                        context={"product_id": product_id, "tenant_key": self.tenant_key},
                    )

                file_size = len(content.encode("utf-8"))

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
                await session.flush()

                self._logger.info(f"Created vision document {sanitize(doc.id)} for product {sanitize(product_id)}")

                total_tokens = len(content) // 4

                chunks_created, total_tokens = await self._chunk_document(
                    session, doc, content, auto_chunk, max_tokens, total_tokens
                )

                await self._consolidate_vision(session, product_id)
                await self.evaluate_vision_analysis_complete(session, product_id)

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
            self._logger.info("Duplicate vision document name race for product %s", sanitize(product_id))
            raise AlreadyExistsError(
                message=f"A vision document named '{filename}' already exists for this product.",
                context={"product_id": product_id, "filename": filename, "tenant_key": self.tenant_key},
            ) from e
        except Exception as e:
            self._logger.exception("Failed to upload vision document")
            raise BaseGiljoError(
                message=f"Failed to upload vision document: {e!s}",
                context={"product_id": product_id, "filename": filename, "tenant_key": self.tenant_key},
            ) from e

    async def _chunk_document(
        self, session, doc, content: str, auto_chunk: bool, max_tokens: int, total_tokens: int
    ) -> tuple[int, int]:
        if not auto_chunk:
            return 0, total_tokens

        from giljo_mcp.context_management.chunker import VisionDocumentChunker

        chunker = VisionDocumentChunker(target_chunk_size=max_tokens)

        chunk_result = await chunker.chunk_vision_document(
            session=session, tenant_key=self.tenant_key, vision_document_id=str(doc.id)
        )
        await session.commit()

        chunks_created = chunk_result["chunks_created"]
        total_tokens = chunk_result["total_tokens"]
        self._logger.info(f"Chunked document {doc.id}: {chunks_created} chunks, {total_tokens} tokens")
        return chunks_created, total_tokens

    async def evaluate_vision_analysis_complete(
        self,
        session: AsyncSession,
        product_id: str,
    ) -> bool:
        complete, _missing = await self.evaluate_vision_completion(session, product_id)
        return complete

    async def evaluate_vision_completion(
        self,
        session: AsyncSession,
        product_id: str,
    ) -> tuple[bool, list[str]]:
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
        repo = self._vision_repo
        return await repo.get_by_id(session, self.tenant_key, document_id)

    async def list_documents_by_product(
        self,
        session: AsyncSession,
        product_id: str,
        active_only: bool = True,
    ) -> list:
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
        repo = self._vision_repo
        return await repo.soft_delete(
            session=session,
            tenant_key=self.tenant_key,
            document_id=document_id,
        )

    async def delete_product_document(self, session: AsyncSession, product_id: str, document_id: str) -> None:
        doc = await self._vision_repo.get_by_id(session, self.tenant_key, document_id)
        if doc is None or str(doc.product_id) != str(product_id):
            raise ResourceNotFoundError(
                message="Vision document not found",
                context={"product_id": product_id, "document_id": document_id},
            )
        await self._vision_repo.delete(session, self.tenant_key, document_id)
        await self.evaluate_vision_analysis_complete(session, product_id)

    async def restore_document(
        self,
        session: AsyncSession,
        document_id: str,
    ) -> Any:
        repo = self._vision_repo
        trashed = await repo.get_deleted_by_id(session, self.tenant_key, document_id)
        if trashed is None:
            raise ResourceNotFoundError("Deleted document not found")
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
        repo = self._vision_repo
        return await repo.list_deleted(
            session=session,
            tenant_key=self.tenant_key,
            product_id=product_id,
        )

    async def purge_expired_deleted_documents(self) -> int:
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
