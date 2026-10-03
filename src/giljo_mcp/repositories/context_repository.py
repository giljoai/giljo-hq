# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models import MCPContextIndex


class ContextRepository:

    def __init__(self, db_manager):
        self.db = db_manager

    async def search_chunks(
        self, session: AsyncSession, tenant_key: str, product_id: str, query: str, limit: int = 10
    ) -> list[MCPContextIndex]:
        search_query = text("""
            SELECT id FROM mcp_context_index
            WHERE tenant_key = :tenant_key
              AND product_id = :product_id
              AND (
                content ILIKE :query_pattern
                OR EXISTS (
                  SELECT 1 FROM jsonb_array_elements_text(keywords) AS keyword
                  WHERE keyword ILIKE :query_pattern
                )
              )
              AND (
                vision_document_id IS NULL
                OR NOT EXISTS (
                  SELECT 1 FROM vision_documents vd
                  WHERE vd.id = mcp_context_index.vision_document_id
                    AND vd.deleted_at IS NOT NULL
                )
              )
            ORDER BY
              CASE WHEN content ILIKE :exact_pattern THEN 1 ELSE 2 END,
              chunk_order
            LIMIT :limit
        """)

        result = await session.execute(
            search_query,
            {
                "tenant_key": tenant_key,
                "product_id": product_id,
                "query_pattern": f"%{query}%",
                "exact_pattern": f"%{query}%",
                "limit": limit,
            },
        )

        ordered_ids = [row.id for row in result]
        if not ordered_ids:
            return []

        stmt = select(MCPContextIndex).where(
            MCPContextIndex.tenant_key == tenant_key,
            MCPContextIndex.id.in_(ordered_ids),
        )
        chunk_result = await session.execute(stmt)
        by_id = {chunk.id: chunk for chunk in chunk_result.scalars()}

        return [by_id[chunk_id] for chunk_id in ordered_ids if chunk_id in by_id]

    async def delete_chunks_by_vision_document(
        self, session: AsyncSession, tenant_key: str, vision_document_id: str
    ) -> int:
        from sqlalchemy import delete

        delete_stmt = delete(MCPContextIndex).where(
            MCPContextIndex.tenant_key == tenant_key, MCPContextIndex.vision_document_id == vision_document_id
        )
        return (await session.execute(delete_stmt)).rowcount
