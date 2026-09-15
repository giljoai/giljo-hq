# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import Product
from giljo_mcp.models.context import MCPContextIndex
from giljo_mcp.tools.chunking import VISION_DELIVERY_BUDGET, EnhancedChunker


VALID_SUMMARY_DEPTHS: frozenset[str] = frozenset({"light", "medium"})


logger = logging.getLogger(__name__)


def estimate_tokens(data: Any) -> int:
    import json

    text = json.dumps(data) if not isinstance(data, str) else data
    return len(text) // 4


def get_max_tokens(chunking: str) -> int:
    if chunking == "none":
        return 0
    return VISION_DELIVERY_BUDGET


def get_max_chunks(chunking: str) -> int:
    if chunking == "none":
        return 0
    return 100


async def _get_summary_response(
    product: Product,
    depth: str,
    product_id: str,
    offset: int = 0,
) -> dict[str, Any]:
    if depth not in VALID_SUMMARY_DEPTHS:
        logger.warning(
            "invalid_depth_for_summary product_id=%s depth=%s operation=%s",
            product_id,
            depth,
            "get_vision_document",
        )
        return {
            "source": "vision_documents",
            "depth": depth,
            "data": {"error": "invalid_depth", "message": f"Invalid depth '{depth}' for summary response"},
            "pagination": None,
        }

    compression = "33%" if depth == "light" else "66%"

    if depth == "light":
        summary_text = product.consolidated_vision_light
        summary_tokens = product.consolidated_vision_light_tokens
    else:
        summary_text = product.consolidated_vision_medium
        summary_tokens = product.consolidated_vision_medium_tokens

    if not summary_text:
        logger.warning(
            "consolidated_summary_not_available product_id=%s depth=%s consolidated_at=%s operation=%s",
            product_id,
            depth,
            product.consolidated_at,
            "get_vision_document",
        )
        return {
            "source": "vision_documents",
            "depth": depth,
            "data": {
                "error": "summary_not_available",
                "message": f"No consolidated {depth} summary available. Run consolidation first.",
            },
            "pagination": None,
        }

    token_count = summary_tokens or estimate_tokens(summary_text)

    if token_count <= VISION_DELIVERY_BUDGET:
        logger.info(
            "consolidated_vision_summary_fetched product_id=%s depth=%s tokens=%s compression=%s consolidated_at=%s consolidated_hash=%s",
            product_id,
            depth,
            token_count,
            compression,
            str(product.consolidated_at) if product.consolidated_at else None,
            product.consolidated_vision_hash[:8] if product.consolidated_vision_hash else None,
        )
        return {
            "source": "vision_documents",
            "depth": depth,
            "data": {
                "summary": summary_text,
                "tokens": token_count,
                "compression": compression,
                "consolidated_at": str(product.consolidated_at) if product.consolidated_at else None,
                "source_hash": product.consolidated_vision_hash,
            },
            "pagination": None,
        }

    chunker = EnhancedChunker(max_tokens=VISION_DELIVERY_BUDGET)
    chunks = chunker.chunk_content(summary_text)
    total_chunks = len(chunks)

    if offset >= total_chunks:
        return {
            "source": "vision_documents",
            "depth": depth,
            "data": {"summary": "", "tokens": 0, "compression": compression},
            "pagination": {
                "total_chunks": total_chunks,
                "offset": offset,
                "limit": 1,
                "has_more": False,
                "next_offset": None,
            },
        }

    selected_chunk = chunks[offset]
    chunk_text = selected_chunk.get("content", "")
    chunk_tokens = estimate_tokens(chunk_text)
    has_more = (offset + 1) < total_chunks
    next_offset = offset + 1 if has_more else None

    logger.info(
        "consolidated_vision_summary_paginated product_id=%s depth=%s total_tokens=%s chunk_tokens=%s chunk_index=%s total_chunks=%s has_more=%s compression=%s",
        product_id,
        depth,
        token_count,
        chunk_tokens,
        offset,
        total_chunks,
        has_more,
        compression,
    )

    return {
        "source": "vision_documents",
        "depth": depth,
        "data": {
            "summary": chunk_text,
            "tokens": chunk_tokens,
            "compression": compression,
            "consolidated_at": str(product.consolidated_at) if product.consolidated_at else None,
            "source_hash": product.consolidated_vision_hash,
        },
        "pagination": {
            "total_chunks": total_chunks,
            "offset": offset,
            "limit": 1,
            "has_more": has_more,
            "next_offset": next_offset,
        },
    }


async def get_vision_document(
    product_id: str,
    tenant_key: str,
    chunking: str = "medium",
    offset: int = 0,
    limit: int | None = None,
    db_manager: DatabaseManager | None = None,
    _test_session: AsyncSession | None = None,
) -> dict[str, Any]:
    logger.info(
        "fetching_vision_document_context product_id=%s tenant_key=%s depth=%s offset=%s limit=%s",
        product_id,
        tenant_key,
        chunking,
        offset,
        limit,
    )

    if chunking == "none":
        return {
            "source": "vision_documents",
            "depth": chunking,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_chunks": 0,
                "offset": offset,
                "limit": 0,
                "returned_chunks": 0,
                "has_more": False,
                "next_offset": None,
            },
        }

    if db_manager is None and _test_session is None:
        logger.error("db_manager is required operation=get_vision_document")
        raise ValueError("db_manager parameter is required")

    return await _get_vision_document_with_session(
        product_id=product_id,
        tenant_key=tenant_key,
        chunking=chunking,
        offset=offset,
        limit=limit,
        db_manager=db_manager,
        session=_test_session,
    )


async def _get_vision_document_with_session(
    product_id: str,
    tenant_key: str,
    chunking: str,
    offset: int,
    limit: int | None,
    db_manager: DatabaseManager | None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if session is not None:
        return await _execute_vision_query(
            session=session,
            product_id=product_id,
            tenant_key=tenant_key,
            chunking=chunking,
            offset=offset,
            limit=limit,
            db_manager=db_manager,
        )

    async with db_manager.get_session_async() as new_session:
        return await _execute_vision_query(
            session=new_session,
            product_id=product_id,
            tenant_key=tenant_key,
            chunking=chunking,
            offset=offset,
            limit=limit,
            db_manager=db_manager,
        )


async def _fetch_active_vision_docs(
    session: AsyncSession,
    product_id: str,
    tenant_key: str,
    chunking: str,
    offset: int,
    limit: int | None,
    db_manager: DatabaseManager | None,
) -> tuple[list | None, dict[str, Any] | None]:
    stmt = (
        select(Product)
        .options(selectinload(Product.vision_documents))
        .where(Product.id == product_id, Product.tenant_key == tenant_key)
    )
    result = await session.execute(stmt)
    product = result.scalar_one_or_none()

    if not product:
        logger.warning(
            "product_not_found product_id=%s tenant_key=%s operation=get_vision_document",
            product_id,
            tenant_key,
        )
        return None, {
            "source": "vision_documents",
            "depth": chunking,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_chunks": 0,
                "offset": offset,
                "limit": limit or 0,
                "returned_chunks": 0,
                "has_more": False,
                "next_offset": None,
                "error": "product_not_found",
            },
        }

    if not product.vision_documents:
        logger.debug("no_vision_documents product_id=%s operation=get_vision_document", product_id)
        return None, {
            "source": "vision_documents",
            "depth": chunking,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_chunks": 0,
                "offset": offset,
                "limit": limit or 0,
                "returned_chunks": 0,
                "has_more": False,
                "next_offset": None,
            },
        }

    active_docs = [doc for doc in product.vision_documents if doc.is_active and doc.deleted_at is None]
    if not active_docs:
        logger.debug("no_active_vision_documents product_id=%s operation=get_vision_document", product_id)
        return None, {
            "source": "vision_documents",
            "depth": chunking,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_chunks": 0,
                "offset": offset,
                "limit": limit or 0,
                "returned_chunks": 0,
                "has_more": False,
                "next_offset": None,
            },
        }

    if chunking in ("light", "medium"):
        response = await _get_summary_response(
            product=product,
            depth=chunking,
            product_id=product_id,
            offset=offset,
        )
        return None, response

    return active_docs, None


def _select_chunks_by_token_budget(
    all_chunks: list,
    offset: int,
    max_chunks: int,
    max_tokens: int,
) -> list[dict[str, Any]]:
    total_chunks = len(all_chunks)
    paginated_chunks = all_chunks[offset : offset + max_chunks] if offset < total_chunks else []

    selected_chunks: list[dict[str, Any]] = []
    total_tokens = 0

    for chunk in paginated_chunks:
        chunk_tokens = chunk.token_count if chunk.token_count else estimate_tokens(chunk.content)

        if total_tokens + chunk_tokens > max_tokens:
            logger.debug(
                "token_budget_reached total_tokens=%s max_tokens=%s chunks_selected=%s operation=%s",
                total_tokens,
                max_tokens,
                len(selected_chunks),
                "get_vision_document",
            )
            break

        selected_chunks.append({"content": chunk.content, "chunk_order": chunk.chunk_order, "tokens": chunk_tokens})
        total_tokens += chunk_tokens

    return selected_chunks


async def _execute_vision_query(
    session: AsyncSession,
    product_id: str,
    tenant_key: str,
    chunking: str,
    offset: int,
    limit: int | None,
    db_manager: DatabaseManager | None,
) -> dict[str, Any]:
    active_docs, early_response = await _fetch_active_vision_docs(
        session=session,
        product_id=product_id,
        tenant_key=tenant_key,
        chunking=chunking,
        offset=offset,
        limit=limit,
        db_manager=db_manager,
    )
    if early_response is not None:
        return early_response


    chunked_docs = [doc for doc in active_docs if doc.chunked and doc.chunk_count > 0]

    if not chunked_docs:
        raw_docs = [doc for doc in active_docs if doc.vision_document]

        if not raw_docs:
            logger.warning(
                "no_vision_content_available product_id=%s total_docs=%s operation=%s",
                product_id,
                len(active_docs),
                "get_vision_document",
            )
            return {
                "source": "vision_documents",
                "depth": chunking,
                "data": {
                    "error": "content_not_available",
                    "message": "No vision document content available. Upload a document first.",
                },
                "pagination": None,
            }

        doc_name_map = {str(doc.id): doc.document_name for doc in active_docs}
        parts: list[str] = []
        for doc in raw_docs:
            name = doc_name_map.get(str(doc.id), "Untitled")
            if len(raw_docs) > 1:
                parts.append(f"# {name}\n{doc.vision_document}")
            else:
                parts.append(doc.vision_document)

        full_text = "\n\n".join(parts)
        total_tokens = estimate_tokens(full_text)
        max_tokens = get_max_tokens(chunking)

        chars_per_token = 4
        max_chars = max_tokens * chars_per_token
        text_offset = offset * chars_per_token if offset else 0
        page_text = full_text[text_offset : text_offset + max_chars]
        page_tokens = estimate_tokens(page_text)
        has_more = (text_offset + len(page_text)) < len(full_text)
        next_offset = (text_offset + len(page_text)) // chars_per_token if has_more else None

        logger.info(
            "vision_raw_content_fetched product_id=%s depth=%s total_docs=%s total_tokens=%s page_tokens=%s has_more=%s",
            product_id,
            chunking,
            len(raw_docs),
            total_tokens,
            page_tokens,
            has_more,
        )

        return {
            "source": "vision_documents",
            "depth": chunking,
            "data": {
                "content": page_text,
                "tokens": page_tokens,
                "total_tokens": total_tokens,
                "document_count": len(raw_docs),
            },
            "pagination": {
                "offset": offset,
                "has_more": has_more,
                "next_offset": next_offset,
            },
        }

    vision_doc_ids = [doc.id for doc in chunked_docs]
    chunk_stmt = (
        select(MCPContextIndex)
        .where(MCPContextIndex.tenant_key == tenant_key, MCPContextIndex.vision_document_id.in_(vision_doc_ids))
        .order_by(MCPContextIndex.chunk_order)
    )

    chunk_result = await session.execute(chunk_stmt)
    all_chunks = chunk_result.scalars().all()

    if not all_chunks:
        logger.warning(
            "chunks_marked_but_not_found product_id=%s vision_doc_ids=%s operation=%s",
            product_id,
            [str(vid) for vid in vision_doc_ids],
            "get_vision_document",
        )
        return {
            "source": "vision_documents",
            "depth": chunking,
            "data": [],
            "metadata": {
                "product_id": product_id,
                "tenant_key": tenant_key,
                "total_chunks": 0,
                "offset": offset,
                "limit": limit or 0,
                "returned_chunks": 0,
                "has_more": False,
                "next_offset": None,
                "error": "chunks_not_found",
            },
        }

    max_chunks = get_max_chunks(chunking) if limit is None else limit
    max_tokens = get_max_tokens(chunking)
    total_chunks = len(all_chunks)

    selected_chunks = _select_chunks_by_token_budget(
        all_chunks=all_chunks,
        offset=offset,
        max_chunks=max_chunks,
        max_tokens=max_tokens,
    )

    has_more = (offset + len(selected_chunks)) < total_chunks
    next_offset = offset + len(selected_chunks) if has_more else None

    logger.info(
        "vision_chunks_fetched product_id=%s tenant_key=%s depth=%s offset=%s limit=%s returned_chunks=%s total_chunks=%s has_more=%s total_tokens=%s max_tokens=%s",
        product_id,
        tenant_key,
        chunking,
        offset,
        max_chunks,
        len(selected_chunks),
        total_chunks,
        has_more,
        sum(c["tokens"] for c in selected_chunks),
        max_tokens,
    )

    return {
        "source": "vision_documents",
        "depth": chunking,
        "data": selected_chunks,
        "pagination": {
            "total_chunks": total_chunks,
            "offset": offset,
            "limit": max_chunks,
            "has_more": has_more,
            "next_offset": next_offset,
        },
    }
