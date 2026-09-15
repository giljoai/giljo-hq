# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from giljo_mcp.auth.dependencies import get_current_active_user

from giljo_mcp.models.auth import User
from giljo_mcp.schemas.service_responses import ProductStatistics
from giljo_mcp.services import ProductService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_product_service
from .models import (
    DeletedProductResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    VisionSummarySchema,
)


logger = logging.getLogger(__name__)
router = APIRouter()

_PURGE_RETENTION_DAYS = 10


def _build_product_response(product, stats=None, override_active=None) -> ProductResponse:
    from giljo_mcp.services.vision_hash import compute_vision_inputs_hash

    from .models import ArchitectureSchema, TechStackSchema, TestConfigSchema

    ts = product.tech_stack
    tech_stack = (
        TechStackSchema(
            programming_languages=ts.programming_languages,
            frontend_frameworks=ts.frontend_frameworks,
            backend_frameworks=ts.backend_frameworks,
            databases_storage=ts.databases_storage,
            infrastructure=ts.infrastructure,
            dev_tools=ts.dev_tools,
        )
        if ts
        else None
    )

    arch = product.architecture
    architecture = (
        ArchitectureSchema(
            primary_pattern=arch.primary_pattern,
            design_patterns=arch.design_patterns,
            api_style=arch.api_style,
            architecture_notes=arch.architecture_notes,
            coding_conventions=arch.coding_conventions,
        )
        if arch
        else None
    )

    tc = product.test_config
    test_config = (
        TestConfigSchema(
            quality_standards=tc.quality_standards,
            test_strategy=tc.test_strategy,
            coverage_target=tc.coverage_target or 80,
            testing_frameworks=tc.testing_frameworks,
        )
        if tc
        else None
    )

    pm = product.product_memory
    if pm is None:
        pm = {"git_integration": {}, "sequential_history": [], "context": {}}

    is_active = override_active if override_active is not None else product.is_active

    return ProductResponse(
        id=str(product.id),
        name=product.name,
        slug=product.slug,
        description=product.description,
        vision_path=None,
        project_path=product.project_path,
        created_at=product.created_at,
        updated_at=product.updated_at,
        project_count=stats.project_count if stats else 0,
        task_count=stats.task_count if stats else 0,
        has_vision=stats.has_vision if stats else False,
        unresolved_tasks=stats.unresolved_tasks if stats else 0,
        unfinished_projects=stats.unfinished_projects if stats else 0,
        vision_documents_count=stats.vision_documents_count if stats else 0,
        tech_stack=tech_stack,
        architecture=architecture,
        test_config=test_config,
        core_features=product.core_features,
        brand_guidelines=product.brand_guidelines,
        extraction_custom_instructions=product.extraction_custom_instructions,
        is_active=is_active,
        is_default=product.is_default,
        product_memory=pm,
        target_platforms=product.target_platforms or ["all"],
        vision_analysis_complete=bool(product.vision_analysis_complete),
        consolidated_vision_light=product.consolidated_vision_light,
        consolidated_vision_medium=product.consolidated_vision_medium,
        consolidated_vision_light_tokens=product.consolidated_vision_light_tokens,
        consolidated_vision_medium_tokens=product.consolidated_vision_medium_tokens,
        consolidated_vision_hash=product.consolidated_vision_hash,
        consolidated_at=product.consolidated_at,
        vision_inputs_hash=compute_vision_inputs_hash(product.vision_documents),
    )


def _build_product_list_response(product, metrics: dict | None, vision: dict | None) -> ProductListResponse:
    vision = vision or {}
    return ProductListResponse(
        id=str(product.id),
        name=product.name,
        description=product.description,
        created_at=product.created_at,
        updated_at=product.updated_at,
        is_active=product.is_active,
        is_default=product.is_default,
        project_path=product.project_path,
        target_platforms=product.target_platforms or ["all"],
        project_count=metrics["project_count"] if metrics else 0,
        task_count=metrics["task_count"] if metrics else 0,
        has_vision=metrics["has_vision"] if metrics else False,
        unresolved_tasks=metrics["unresolved_tasks"] if metrics else 0,
        unfinished_projects=metrics["unfinished_projects"] if metrics else 0,
        vision_documents_count=metrics["vision_documents_count"] if metrics else 0,
        vision_analysis_complete=bool(product.vision_analysis_complete),
        vision_summary=VisionSummarySchema(
            doc_count=vision.get("doc_count", 0),
            chunked_count=vision.get("chunked_count", 0),
            chunk_total=vision.get("chunk_total", 0),
            embedded_count=vision.get("embedded_count", 0),
        ),
    )


def _stats_from_metrics(product, metrics: dict) -> ProductStatistics:
    return ProductStatistics(
        product_id=str(product.id),
        name=product.name,
        is_active=product.is_active,
        project_count=metrics["project_count"],
        unfinished_projects=metrics["unfinished_projects"],
        task_count=metrics["task_count"],
        unresolved_tasks=metrics["unresolved_tasks"],
        vision_documents_count=metrics["vision_documents_count"],
        has_vision=metrics["has_vision"],
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@router.post("/", response_model=ProductResponse)
async def create_product(
    request: ProductCreate,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """
    Create a new product.

    Uses ProductService.create_product() for database operations.
    """
    product = await service.create_product(
        name=request.name,
        description=request.description,
        project_path=request.project_path,
        tech_stack=request.tech_stack.model_dump() if request.tech_stack else None,
        architecture=request.architecture.model_dump() if request.architecture else None,
        test_config=request.test_config.model_dump() if request.test_config else None,
        core_features=request.core_features,
        brand_guidelines=request.brand_guidelines,
        target_platforms=request.target_platforms,
    )

    stats = await service.memory.get_product_statistics(str(product.id))

    return _build_product_response(product, stats)


@router.get("/", response_model=list[ProductListResponse])
async def list_products(
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
    include_inactive: bool = Query(
        default=True, description="Include inactive products (default: True, always show all)"
    ),
) -> list[ProductListResponse]:
    """
    List all products for the current tenant.

    BE-6066 P4: returns the LEAN ``ProductListResponse`` — identity/flags/counts +
    vision AGGREGATES, NOT the full detail graph. The 4 heavy relations
    (tech_stack / architecture / test_config / vision_documents) are no longer
    eager-loaded or serialized here; full detail loads on demand via
    ``GET /products/{id}`` when the user opens Edit/Details.
    """
    products = await service.list_products(include_inactive=include_inactive, lean=True)

    logger.debug("Found %d products", len(products))

    product_ids = [str(p.id) for p in products]
    stats_map = await service.memory.get_product_statistics_bulk(product_ids)
    vision_map = await service.memory.get_vision_summary_bulk(product_ids)

    responses = []
    for product in products:
        pid = str(product.id)
        responses.append(_build_product_list_response(product, stats_map.get(pid), vision_map.get(pid)))

    return responses


@router.get("/deleted", response_model=list[DeletedProductResponse])
async def list_deleted_products(
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> list[DeletedProductResponse]:
    """
    List soft-deleted products (Handover 0070).

    Uses ProductService.list_deleted_products() for database operations.
    Handover 0731d: Purge date computation moved from service to endpoint layer.
    """
    products = await service.lifecycle.list_deleted_products()

    product_ids = [str(p.id) for p in products]
    stats_map = await service.memory.get_product_statistics_bulk(product_ids)

    now = datetime.now(UTC)
    result = []
    for p in products:
        purge_date = p.deleted_at + timedelta(days=_PURGE_RETENTION_DAYS)
        days_until_purge = max(0, (purge_date - now).days)
        stats = stats_map.get(str(p.id)) or {}

        result.append(
            DeletedProductResponse(
                id=str(p.id),
                name=p.name,
                description=p.description,
                deleted_at=p.deleted_at,
                days_until_purge=days_until_purge,
                purge_date=purge_date,
                project_count=stats.get("project_count", 0),
                vision_documents_count=stats.get("vision_documents_count", 0),
            )
        )

    return result


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """
    Get product by ID.

    Uses ProductService.get_product() for database operations.
    """
    product = await service.get_product(product_id=product_id)
    stats = await service.memory.get_product_statistics(str(product.id))

    pm = product.product_memory
    if pm is None:
        logger.warning("Product %s: product_memory is None, using default", sanitize(product_id))
    logger.info("Product %s: product_memory keys=%s", sanitize(product_id), list((pm or {}).keys()))

    return _build_product_response(product, stats)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    updates: ProductUpdate,
    current_user: User = Depends(get_current_active_user),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """
    Update an existing product.

    Uses ProductService.update_product() for database operations.
    """
    update_data = updates.model_dump(exclude_unset=True)

    product = await service.update_product(product_id, force=True, **update_data)

    stats = await service.memory.get_product_statistics(str(product.id))

    logger.info("Updated product %s", sanitize(product_id))

    return _build_product_response(product, stats)
