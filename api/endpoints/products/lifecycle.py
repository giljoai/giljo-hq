# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_tenant_key
from api.endpoints._boundary_types import IdPath
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
from giljo_mcp.services import ProductService
from giljo_mcp.utils.log_sanitizer import sanitize

from .crud import _build_product_response, _stats_from_metrics
from .dependencies import get_product_service
from .models import (
    ActiveProductRefreshResponse,
    CascadeImpact,
    ContextUpdateProjectResponse,
    ProductActivationResponse,
    ProductDeleteResponse,
    ProductPurgeResponse,
    ProductResponse,
    VisionDocumentStatsResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{product_id}/activate", response_model=ProductActivationResponse)
async def activate_product(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductActivationResponse:
    """
    Show a product's tab. No longer deactivates other products or
    pauses their projects/jobs -- several products may be shown at once.

    Uses ProductService.activate_product() for database operations.
    Updated response to match frontend expectations.
    """
    logger.info("User %s activating product %s", sanitize(current_user.username), sanitize(product_id))

    try:
        default_product = await service.get_default_product(eager_load=False)
        previous_active_id = None
        if default_product:
            previous_active_id = str(default_product.id)

        await service.activate_product(product_id)

        product = await service.get_product(product_id)

        stats_map = await service.memory.get_product_statistics_bulk([str(product.id)])
        metrics = stats_map.get(str(product.id))
        stats = _stats_from_metrics(product, metrics) if metrics else None

        product_response = _build_product_response(product, stats, override_active=True)

        deactivated_projects = []

        return ProductActivationResponse(
            product_id=str(product.id),
            previous_active_product_id=previous_active_id,
            product=product_response,
            message=f"Product '{product.name}' activated successfully",
            deactivated_projects=deactivated_projects,
        )

    finally:
        try:
            from api.app_state import state

            if getattr(state, "event_bus", None):
                await state.event_bus.publish(
                    "product:status:changed",
                    {
                        "tenant_key": current_user.tenant_key,
                        "product_id": product_id,
                        "is_active": True,
                    },
                )
        except Exception as pub_err:  # noqa: BLE001 - fire-and-forget WS event
            logger.warning("Failed to publish product activation event: %s", sanitize(str(pub_err)))


@router.post("/{product_id}/deactivate", response_model=ProductResponse)
async def deactivate_product(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """
    Hide a product's tab. No longer pauses its projects or jobs.

    Uses ProductService.deactivate_product() for database operations.
    """
    logger.info("User %s deactivating product %s", sanitize(current_user.username), sanitize(product_id))

    try:
        await service.deactivate_product(product_id)

        product = await service.get_product(product_id)
        stats = await service.memory.get_product_statistics(str(product.id))

        return _build_product_response(product, stats)
    finally:
        try:
            from api.app_state import state

            if getattr(state, "event_bus", None):
                await state.event_bus.publish(
                    "product:status:changed",
                    {
                        "tenant_key": current_user.tenant_key,
                        "product_id": product_id,
                        "is_active": False,
                    },
                )
        except Exception as pub_err:  # noqa: BLE001 - fire-and-forget WS event
            logger.warning("Failed to publish product deactivation event: %s", sanitize(str(pub_err)))


@router.post("/{product_id}/set-default", response_model=ProductResponse)
async def set_default_product(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """
    Set the tenant's DEFAULT product (operator ruling 2026-08-29):
    where an unscoped read resolves. Independent of shown/hidden -- does not
    require the target to be shown (D2: hidden is still a fully valid
    default), and never touches projects or jobs.

    No UI control calls this endpoint yet -- the operator is separately
    deciding the exact affordance (e.g. whether the product-card play button
    becomes a "Default product" checkbox). This exists so the capability is
    complete and testable ahead of that UI decision.

    Uses ProductService.set_default_product() for database operations.
    """
    logger.info("User %s setting default product %s", sanitize(current_user.username), sanitize(product_id))

    await service.set_default_product(product_id)

    product = await service.get_product(product_id)
    stats = await service.memory.get_product_statistics(str(product.id))
    return _build_product_response(product, stats)


@router.delete("/{product_id}", response_model=ProductDeleteResponse)
async def delete_product(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductDeleteResponse:
    """
    Soft delete a product.

    Uses ProductService.delete_product() for database operations.
    Returns enhanced response with deletion context (was_active, remaining count).
    """
    logger.info("User %s deleting product %s", sanitize(current_user.username), sanitize(product_id))

    product = await service.get_product(product_id)
    was_active = product.is_active

    await service.lifecycle.delete_product(product_id)

    remaining_products = await service.list_products()
    remaining_count = len(remaining_products)

    return ProductDeleteResponse(
        message="Product soft-deleted successfully",
        deleted_product_id=product_id,
        was_active=was_active,
        remaining_products_count=remaining_count,
        new_active_product=None,
    )


@router.delete("/{product_id}/purge")
async def purge_product(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
):
    """
    Permanently delete a product and ALL related data.

    This is the nuclear option — no recovery possible.
    Cascades to: projects, tasks, vision documents, memory entries, context chunks,
    tech_stack, architecture, test_config.
    """
    logger.info("User %s permanently deleting product %s", sanitize(current_user.username), sanitize(product_id))
    result = await service.lifecycle.purge_product(product_id)
    return ProductPurgeResponse(**result)


@router.post("/{product_id}/restore", response_model=ProductResponse)
async def restore_product(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """
    Restore a soft-deleted product.

    Uses ProductService.restore_product() for database operations.
    """
    logger.info(f"User {sanitize(current_user.username)} restoring product {sanitize(product_id)}")

    await service.lifecycle.restore_product(product_id)

    product = await service.get_product(product_id)
    stats = await service.memory.get_product_statistics(str(product.id))

    return _build_product_response(product, stats)


@router.get("/{product_id}/cascade-impact", response_model=CascadeImpact)
async def get_cascade_impact(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> CascadeImpact:
    """
    Get cascade impact analysis for product deletion.

    Uses ProductService.get_cascade_impact() for database operations.
    """
    logger.debug(f"User {sanitize(current_user.username)} checking cascade impact for product {sanitize(product_id)}")

    impact = await service.memory.get_cascade_impact(product_id)

    return CascadeImpact(
        product_id=impact.product_id,
        product_name=impact.product_name,
        total_projects=impact.total_projects,
        total_tasks=impact.total_tasks,
        total_vision_documents=impact.total_vision_documents,
        warning=impact.warning,
    )


@router.get("/refresh-active", response_model=ActiveProductRefreshResponse)
async def refresh_active_product(
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ActiveProductRefreshResponse:
    """
    Refresh default-product information. The response carries
    ``has_active_product`` and ``product``.

    Uses ProductService.get_default_product() for database operations.
    """
    logger.debug(f"User {current_user.username} refreshing default product")

    product = await service.get_default_product()

    if not product:
        return ActiveProductRefreshResponse(has_active_product=False, product=None)

    stats_map = await service.memory.get_product_statistics_bulk([str(product.id)])
    metrics = stats_map.get(str(product.id))
    stats = _stats_from_metrics(product, metrics) if metrics else None

    return ActiveProductRefreshResponse(
        has_active_product=True,
        product=_build_product_response(product, stats),
    )


@router.get("/active/vision-stats", response_model=VisionDocumentStatsResponse)
async def get_vision_document_stats(
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
    db: AsyncSession = Depends(get_db_session),
    tenant_key: str = Depends(get_tenant_key),
) -> VisionDocumentStatsResponse:
    """
    Get vision document statistics for the tenant's DEFAULT product.

    Returns token counts and metadata for the default product's vision document.
    Used by frontend to dynamically display context depth options with actual token counts.

    Dynamic vision document token counts for context depth configuration.
    Resolves is_default, not is_active -- see ProductService.get_default_product.
    """
    logger.debug(f"User {current_user.username} requesting vision stats for default product")

    product = await service.get_default_product()

    if not product:
        raise HTTPException(status_code=404, detail="No default product found")

    product_id = str(product.id)
    product_name = product.name

    from sqlalchemy import and_, select

    from giljo_mcp.models import VisionDocument

    stmt = (
        select(VisionDocument)
        .where(
            and_(
                VisionDocument.tenant_key == tenant_key,
                VisionDocument.product_id == product_id,
                VisionDocument.is_active == True,  # noqa: E712
                VisionDocument.deleted_at.is_(None),
            )
        )
        .order_by(VisionDocument.created_at.desc())
    )

    result_db = await db.execute(stmt)
    vision_docs = result_db.scalars().all()

    if not vision_docs:
        return VisionDocumentStatsResponse(
            product_id=product_id,
            product_name=product_name,
            has_vision_document=False,
            total_tokens=0,
            chunk_count=0,
            is_summarized=False,
            summary_tokens=0,
        )

    total_tokens = sum(doc.total_tokens or 0 for doc in vision_docs)
    chunk_count = sum(doc.chunk_count or 0 for doc in vision_docs)
    is_summarized = any((doc.meta_data or {}).get("is_summarized", False) for doc in vision_docs)
    summary_tokens = sum((doc.meta_data or {}).get("summary_tokens", 0) for doc in vision_docs)

    return VisionDocumentStatsResponse(
        product_id=product_id,
        product_name=product_name,
        has_vision_document=True,
        total_tokens=total_tokens,
        chunk_count=chunk_count,
        is_summarized=is_summarized,
        summary_tokens=summary_tokens,
    )


@router.get("/{product_id}/context_update_project", response_model=ContextUpdateProjectResponse)
async def get_context_update_project(
    product_id: IdPath,
    current_user: User = Depends(get_current_active_user),
    tenant_key: str = Depends(get_tenant_key),
    db: AsyncSession = Depends(get_db_session),
) -> ContextUpdateProjectResponse:
    """Return the open CTX project for this product, or 404 if none exists."""
    from sqlalchemy import select

    from giljo_mcp.domain.project_status import ProjectStatus
    from giljo_mcp.models import Project, TaxonomyType
    from giljo_mcp.repositories.product_repository import ProductRepository
    from giljo_mcp.services.vision_hash import (
        compute_vision_inputs_hash,
        vision_inputs_hash_matches_consolidated,
    )

    product_repo = ProductRepository()
    product = await product_repo.get_by_id(db, tenant_key, product_id, eager_load=True)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")

    terminal = (
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.TERMINATED,
        ProjectStatus.DELETED,
    )
    stmt = (
        select(Project)
        .join(TaxonomyType, Project.project_type_id == TaxonomyType.id)
        .where(
            Project.tenant_key == tenant_key,
            Project.product_id == product_id,
            TaxonomyType.abbreviation == "CTX",
            Project.status.notin_(terminal),
        )
        .order_by(Project.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="No open CTX project for this product.")

    vision_inputs_hash = compute_vision_inputs_hash(product.vision_documents)
    return ContextUpdateProjectResponse(
        product_id=product_id,
        project_id=str(project.id),
        taxonomy_alias=project.taxonomy_alias,
        status=project.status,
        created_at=project.created_at,
        vision_inputs_hash=vision_inputs_hash,
        consolidated_vision_hash=product.consolidated_vision_hash,
        hash_matches=vision_inputs_hash_matches_consolidated(vision_inputs_hash, product.consolidated_vision_hash),
    )
