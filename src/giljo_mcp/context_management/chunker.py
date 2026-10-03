# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

import tiktoken

from giljo_mcp.exceptions import ContextError
from giljo_mcp.tools.chunking import VISION_DELIVERY_BUDGET, EnhancedChunker
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class VisionDocumentChunker:

    def __init__(self, target_chunk_size: int = VISION_DELIVERY_BUDGET):
        self.target_chunk_size = target_chunk_size

        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except (ValueError, KeyError, ImportError):
            logger.exception("Failed to initialize tiktoken encoding")
            raise

        max_tokens_for_enhanced = target_chunk_size
        self.enhanced_chunker = EnhancedChunker(max_tokens=max_tokens_for_enhanced)

        logger.info(f"VisionDocumentChunker initialized with target size: {target_chunk_size} tokens")

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0

        return len(self.encoding.encode(text, disallowed_special=()))

    def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
        if not text or not text.strip():
            return []

        base_keywords = self.enhanced_chunker.extract_keywords(text, max_keywords)

        additional_terms = [
            "Vision",
            "Mission",
            "Architecture",
            "Implementation",
            "Testing",
            "Deployment",
            "Security",
            "Performance",
            "Scalability",
            "Integration",
            "Configuration",
        ]

        text_lower = text.lower()
        for term in additional_terms:
            if term.lower() in text_lower and term not in base_keywords:
                base_keywords.append(term)
                if len(base_keywords) >= max_keywords:
                    break

        return base_keywords[:max_keywords]

    def generate_summary(self, text: str, max_length: int = 200) -> str:
        if not text:
            return ""

        text = text.strip()

        if len(text) <= max_length:
            return text

        truncated = text[:max_length]

        sentence_ends = [".", "!", "?", "\n"]
        last_sentence = -1

        for end_char in sentence_ends:
            pos = truncated.rfind(end_char)
            last_sentence = max(last_sentence, pos)

        if last_sentence > 0:
            return truncated[: last_sentence + 1].strip()

        last_space = truncated.rfind(" ")
        if last_space > 0:
            return truncated[:last_space].strip() + "..."

        return truncated.strip() + "..."

    def chunk_document(self, content: str, product_id: str) -> list[dict[str, Any]]:
        if not content or not content.strip():
            return []

        enhanced_chunks = self.enhanced_chunker.chunk_content(content, document_name=f"product_{product_id}")

        if not enhanced_chunks:
            return []

        processed_chunks = []

        for _, chunk in enumerate(enhanced_chunks):
            chunk_content = chunk["content"]

            if not chunk_content.strip():
                continue

            token_count = self.count_tokens(chunk_content)

            keywords = self.extract_keywords(chunk_content, max_keywords=10)

            summary = self.generate_summary(chunk_content, max_length=200)

            processed_chunk = {
                "chunk_number": len(processed_chunks) + 1,
                "total_chunks": len(enhanced_chunks),
                "content": chunk_content,
                "tokens": token_count,
                "keywords": keywords,
                "summary": summary,
                "product_id": product_id,
            }

            processed_chunks.append(processed_chunk)

        total_chunks = len(processed_chunks)
        for chunk in processed_chunks:
            chunk["total_chunks"] = total_chunks

        logger.info(
            f"Chunked document for product {product_id}: "
            f"{total_chunks} chunks, "
            f"{sum(c['tokens'] for c in processed_chunks)} total tokens"
        )

        return processed_chunks

    async def chunk_vision_document(self, session, tenant_key: str, vision_document_id: str) -> dict[str, Any]:
        try:
            from giljo_mcp.models import MCPContextIndex
            from giljo_mcp.repositories.context_repository import ContextRepository
            from giljo_mcp.repositories.vision_document_repository import VisionDocumentRepository
        except ImportError as e:
            logger.exception("Failed to import repositories")
            raise ContextError(f"Import error: {e}") from e

        vision_repo = VisionDocumentRepository(db_manager=None)
        context_repo = ContextRepository(db_manager=None)

        doc = await vision_repo.get_by_id(session, tenant_key, vision_document_id)
        if not doc:
            error_msg = f"Vision document {vision_document_id} not found for tenant {tenant_key}"
            logger.error(sanitize(error_msg))
            raise ContextError(error_msg)

        content = doc.vision_document or ""

        if not content or not content.strip():
            error_msg = f"Document {vision_document_id} has no content to chunk"
            logger.error(error_msg)
            raise ContextError(error_msg)

        deleted_count = await context_repo.delete_chunks_by_vision_document(session, tenant_key, vision_document_id)

        logger.info(f"Deleted {deleted_count} existing chunks for document {vision_document_id}")

        chunks = self.chunk_document(content, doc.product_id)

        if not chunks:
            error_msg = f"No chunks generated for document {vision_document_id}"
            logger.warning(error_msg)
            return {
                "success": True,
                "document_id": vision_document_id,
                "document_name": doc.document_name,
                "chunks_created": 0,
                "total_tokens": 0,
                "old_chunks_deleted": deleted_count,
            }

        from giljo_mcp.schemas.jsonb_validators import validate_context_keywords

        total_tokens = 0
        for idx, chunk_data in enumerate(chunks):
            chunk_record = MCPContextIndex(
                tenant_key=tenant_key,
                product_id=doc.product_id,
                vision_document_id=vision_document_id,
                content=chunk_data["content"],
                keywords=validate_context_keywords(chunk_data.get("keywords", [])) or [],
                token_count=chunk_data.get("tokens", 0),
                chunk_order=idx,
                summary=chunk_data.get("summary", None),
            )
            session.add(chunk_record)
            total_tokens += chunk_data.get("tokens", 0)

        await session.flush()

        await vision_repo.mark_chunked(session, tenant_key, vision_document_id, len(chunks), total_tokens)

        logger.info(
            f"Successfully chunked document {vision_document_id}: "
            f"{len(chunks)} chunks, {total_tokens} tokens, "
            f"{deleted_count} old chunks deleted"
        )

        return {
            "success": True,
            "document_id": vision_document_id,
            "document_name": doc.document_name,
            "chunks_created": len(chunks),
            "total_tokens": total_tokens,
            "old_chunks_deleted": deleted_count,
        }
