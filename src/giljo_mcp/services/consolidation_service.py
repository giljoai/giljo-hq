# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.schemas.service_responses import ConsolidationResult, SummaryLevel
from giljo_mcp.services.vision_hash import build_vision_aggregate
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ConsolidatedVisionService:

    def __init__(self):
        self._repo = ProjectRepository()

    async def consolidate_vision_documents(
        self, product_id: str, session: AsyncSession, tenant_key: str, force: bool = False
    ) -> ConsolidationResult:
        with tenant_session_context(session, tenant_key):
            product = await self._repo.get_product_with_vision_docs(session, tenant_key, product_id)

        if not product:
            logger.warning("consolidate_vision_documents.product_not_found: product_id=%s", sanitize(product_id))
            raise ResourceNotFoundError(
                message="Product not found", error_code="PRODUCT_NOT_FOUND", context={"product_id": product_id}
            )

        aggregate_text, source_doc_ids, aggregate_hash = self._build_aggregate(product)

        if not force and product.consolidated_vision_hash == aggregate_hash:
            logger.info(
                "consolidate_vision_documents.no_changes: product_id=%s hash=%s", sanitize(product_id), aggregate_hash
            )
            raise ValidationError(
                message="No changes detected in vision documents",
                error_code="NO_CHANGES",
                context={"product_id": product_id, "hash": aggregate_hash},
            )

        product.consolidated_vision_hash = aggregate_hash
        product.consolidated_at = datetime.now(UTC)
        with tenant_session_context(session, tenant_key):
            await session.commit()

        logger.info(
            "consolidate_vision_documents.hash_updated: product_id=%s source_docs=%d aggregate_chars=%d",
            sanitize(product_id),
            len(source_doc_ids),
            len(aggregate_text),
        )

        return ConsolidationResult(
            light=SummaryLevel(
                summary=product.consolidated_vision_light or "",
                tokens=product.consolidated_vision_light_tokens or 0,
            ),
            medium=SummaryLevel(
                summary=product.consolidated_vision_medium or "",
                tokens=product.consolidated_vision_medium_tokens or 0,
            ),
            hash=aggregate_hash,
            source_docs=source_doc_ids,
        )

    def _build_aggregate(self, product: Product) -> tuple[str, list[str], str]:
        return build_vision_aggregate(product.vision_documents)
