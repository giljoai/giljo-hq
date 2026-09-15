# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import MCPContextIndex, Product, VisionDocument


class VisionDocumentRepository:

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def create(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
        document_name: str,
        content: str,
        document_type: str = "vision",
        storage_type: str = "inline",
        file_path: str | None = None,
        file_size: int | None = None,
        is_active: bool = True,
        display_order: int = 0,
        version: str = "1.0.0",
        meta_data: dict | None = None,
    ) -> VisionDocument:
        stmt = select(Product).where(Product.id == product_id, Product.tenant_key == tenant_key)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            raise ValueError(f"Product {product_id} not found for tenant {tenant_key}")

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        doc = VisionDocument(
            tenant_key=tenant_key,
            product_id=product_id,
            document_name=document_name,
            vision_document=content,
            vision_path=file_path if storage_type in ("file", "hybrid") else None,
            storage_type=storage_type,
            document_type=document_type,
            content_hash=content_hash,
            file_size=file_size,
            is_active=is_active,
            display_order=display_order,
            version=version,
            chunked=False,
            chunk_count=0,
            meta_data=meta_data or {},
        )

        session.add(doc)
        await session.flush()

        return doc

    async def get_by_id(self, session: AsyncSession, tenant_key: str, document_id: str) -> VisionDocument | None:
        stmt = select(VisionDocument).where(
            VisionDocument.id == document_id,
            VisionDocument.tenant_key == tenant_key,
            VisionDocument.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_deleted_by_id(
        self, session: AsyncSession, tenant_key: str, document_id: str
    ) -> VisionDocument | None:
        stmt = select(VisionDocument).where(
            VisionDocument.id == document_id,
            VisionDocument.tenant_key == tenant_key,
            VisionDocument.deleted_at.isnot(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_deleted(
        self, session: AsyncSession, tenant_key: str, product_id: str | None = None
    ) -> list[VisionDocument]:
        conditions = [VisionDocument.tenant_key == tenant_key, VisionDocument.deleted_at.isnot(None)]
        if product_id is not None:
            conditions.append(VisionDocument.product_id == product_id)
        stmt = select(VisionDocument).where(and_(*conditions)).order_by(VisionDocument.deleted_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_product(
        self, session: AsyncSession, tenant_key: str, product_id: str, active_only: bool = True
    ) -> list[VisionDocument]:
        stmt = select(VisionDocument).where(
            VisionDocument.tenant_key == tenant_key,
            VisionDocument.product_id == product_id,
            VisionDocument.deleted_at.is_(None),
        )

        if active_only:
            stmt = stmt.where(VisionDocument.is_active)

        stmt = stmt.order_by(VisionDocument.display_order, VisionDocument.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_content(
        self, session: AsyncSession, tenant_key: str, document_id: str, new_content: str
    ) -> VisionDocument | None:
        doc = await self.get_by_id(session, tenant_key, document_id)

        if not doc:
            return None

        if doc.storage_type in ("inline", "hybrid"):
            doc.vision_document = new_content

        doc.content_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

        doc.chunked = False
        doc.chunk_count = 0
        doc.total_tokens = None
        doc.chunked_at = None

        doc.updated_at = datetime.now(UTC)

        await session.flush()
        return doc

    async def update_summaries(
        self,
        session: AsyncSession,
        tenant_key: str,
        document_id: str,
        light: str,
        medium: str,
    ) -> VisionDocument | None:
        doc = await self.get_by_id(session, tenant_key, document_id)
        if not doc:
            return None

        doc.summary_light = light
        doc.summary_medium = medium
        doc.summary_light_tokens = len(light.split())
        doc.summary_medium_tokens = len(medium.split())
        doc.is_summarized = True
        doc.updated_at = datetime.now(UTC)

        await session.flush()
        return doc

    async def delete(self, session: AsyncSession, tenant_key: str, document_id: str) -> dict[str, Any]:
        doc = await self.get_by_id(session, tenant_key, document_id)

        if not doc:
            raise ResourceNotFoundError("Document not found")

        stmt = select(MCPContextIndex).where(
            MCPContextIndex.vision_document_id == document_id, MCPContextIndex.tenant_key == tenant_key
        )
        result = await session.execute(stmt)
        chunk_count = len(result.scalars().all())

        document_name = doc.document_name

        await session.delete(doc)
        await session.flush()

        return {
            "success": True,
            "document_id": document_id,
            "document_name": document_name,
            "chunks_deleted": chunk_count,
        }

    async def soft_delete(self, session: AsyncSession, tenant_key: str, document_id: str) -> dict[str, Any]:
        doc = await self.get_by_id(session, tenant_key, document_id)
        if not doc:
            raise ResourceNotFoundError("Document not found")

        stmt = select(MCPContextIndex).where(
            MCPContextIndex.vision_document_id == document_id, MCPContextIndex.tenant_key == tenant_key
        )
        result = await session.execute(stmt)
        chunk_count = len(result.scalars().all())

        document_name = doc.document_name
        doc.deleted_at = datetime.now(UTC)
        await session.flush()

        return {
            "success": True,
            "document_id": document_id,
            "document_name": document_name,
            "chunks_deleted": chunk_count,
        }

    async def hard_delete_trashed(self, session: AsyncSession, tenant_key: str, document_id: str) -> bool:
        doc = await self.get_deleted_by_id(session, tenant_key, document_id)
        if doc is None:
            return False
        await session.delete(doc)
        await session.flush()
        return True

    async def restore(self, session: AsyncSession, tenant_key: str, document_id: str) -> VisionDocument:
        doc = await self.get_deleted_by_id(session, tenant_key, document_id)
        if not doc:
            raise ResourceNotFoundError("Deleted document not found")
        doc.deleted_at = None
        doc.updated_at = datetime.now(UTC)
        await session.flush()
        return doc

    async def mark_chunked(
        self, session: AsyncSession, tenant_key: str, document_id: str, chunk_count: int, total_tokens: int
    ) -> None:
        stmt = select(VisionDocument).where(
            VisionDocument.id == document_id,
            VisionDocument.tenant_key == tenant_key,
        )
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()

        if doc:
            doc.chunked = True
            doc.chunk_count = chunk_count
            doc.total_tokens = total_tokens
            doc.chunked_at = datetime.now(UTC)

            if doc.vision_document:
                doc.content_hash = hashlib.sha256(doc.vision_document.encode("utf-8")).hexdigest()

            await session.flush()


    async def get_product_by_id(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
    ) -> Product | None:
        stmt = select(Product).where(
            and_(
                Product.id == product_id,
                Product.tenant_key == tenant_key,
                Product.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
