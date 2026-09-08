# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Project Series-Number Endpoints (INF-6055 extraction from crud.py).

Cohesive group: series-number management for the project taxonomy.

- GET /next-series      - Next available series number for a type
- GET /available-series - Available series numbers (gaps + next) for a type
- GET /check-series     - Whether a specific series number is available
- GET /used-subseries   - Subseries letters already used for a type + series

All endpoints default to the DEFAULT product and delegate the lookup logic to
``api.endpoints.taxonomy_types.crud_ops``. Extracted verbatim from
``api/endpoints/projects/crud.py`` to keep that module under the 800-line
guardrail; paths, params, and response contracts are unchanged.

FE-9502c: each endpoint also accepts an optional ``product_id`` query param
that OVERRIDES the default-product resolution. A caller that omits it keeps
today's default-product-fallback behaviour byte-for-byte (BE-9509's pin
stays valid). The override exists because the tabbed product shell can have
a viewed tab that is not the tenant's single DEFAULT product (FE-9524:
several products may be SHOWN at once, but exactly one is DEFAULT) --
without an explicit override, series/subseries lookups for a non-default tab
would silently resolve against the wrong product's taxonomy. The underlying
service/repo layer already applies ``product_id`` unconditionally and scopes
every query by ``tenant_key`` (BE-9515), so an explicit override is exactly
as tenant-safe as the fallback it replaces.

Router registration order matters: this router is included BEFORE ``crud.router``
in ``__init__.py`` so the static ``/next-series`` etc. paths are matched before
``crud``'s catch-all ``/{project_id}`` route.
"""

import logging

from fastapi import APIRouter, Depends, Query

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.project_service import ProjectService

from .dependencies import get_project_service
from .models import (
    AvailableSeriesResponse,
    NextSeriesResponse,
    SeriesCheckResponse,
    UsedSubseriesResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/next-series", response_model=NextSeriesResponse)
async def next_series_number(
    type_id: str,
    product_id: str | None = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
):
    """Get the next available series number for a project type.

    Scoped to ``product_id`` when given (FE-9502c), else falls back to the
    default product.
    """
    from api.endpoints.taxonomy_types.crud_ops import get_next_series_number
    from giljo_mcp.services.product_service import ProductService

    if product_id is None:
        product_service = ProductService(
            db_manager=project_service.db_manager,
            tenant_key=current_user.tenant_key,
        )
        default_product = await product_service.get_default_product()
        product_id = str(default_product.id) if default_product else None

    async with project_service.db_manager.get_session_async() as session:
        next_num = await get_next_series_number(session, current_user.tenant_key, type_id, product_id)
    return {"next_series_number": next_num}


@router.get("/available-series", response_model=AvailableSeriesResponse)
async def available_series_numbers(
    type_id: str,
    limit: int = 5,
    product_id: str | None = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
):
    """Get available series numbers (gaps + next) for a project type.

    Scoped to ``product_id`` when given (FE-9502c), else falls back to the
    default product.
    """
    from api.endpoints.taxonomy_types.crud_ops import get_available_series_numbers
    from giljo_mcp.services.product_service import ProductService

    if product_id is None:
        product_service = ProductService(
            db_manager=project_service.db_manager,
            tenant_key=current_user.tenant_key,
        )
        default_product = await product_service.get_default_product()
        product_id = str(default_product.id) if default_product else None

    async with project_service.db_manager.get_session_async() as session:
        available = await get_available_series_numbers(session, current_user.tenant_key, type_id, limit, product_id)
    return {"available_series_numbers": available}


@router.get("/check-series", response_model=SeriesCheckResponse)
async def check_series_number(
    type_id: str | None = None,
    # Lookup tolerates up to 6 digits (decision D) so grandfathered 5-digit
    # serials can be queried without a 422. Assignment is capped elsewhere;
    # this is a read/availability check, not a write.
    series_number: int = Query(ge=1, le=999999),
    subseries: str | None = Query(default=None, pattern=r"^[a-z]$"),
    exclude_project_id: str | None = None,
    product_id: str | None = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
):
    """Check if a specific series number is available.

    Scoped to ``product_id`` when given (FE-9502c), else falls back to the
    default product.
    """
    from api.endpoints.taxonomy_types.crud_ops import check_series_available
    from giljo_mcp.services.product_service import ProductService

    if product_id is None:
        product_service = ProductService(
            db_manager=project_service.db_manager,
            tenant_key=current_user.tenant_key,
        )
        default_product = await product_service.get_default_product()
        product_id = str(default_product.id) if default_product else None

    async with project_service.db_manager.get_session_async() as session:
        return await check_series_available(
            session,
            current_user.tenant_key,
            type_id,
            series_number,
            subseries,
            exclude_project_id,
            product_id,
        )


@router.get("/used-subseries", response_model=UsedSubseriesResponse)
async def used_subseries(
    type_id: str | None = None,
    # Lookup tolerates up to 6 digits (decision D) so grandfathered 5-digit
    # serials can be queried without a 422 (read-only availability check).
    series_number: int = Query(ge=1, le=999999),
    exclude_project_id: str | None = None,
    product_id: str | None = None,
    current_user: User = Depends(get_current_active_user),
    project_service: ProjectService = Depends(get_project_service),
):
    """Get subseries letters already used for a type + series_number.

    Scoped to ``product_id`` when given (FE-9502c), else falls back to the
    default product.
    """
    from api.endpoints.taxonomy_types.crud_ops import get_used_subseries
    from giljo_mcp.services.product_service import ProductService

    if product_id is None:
        product_service = ProductService(
            db_manager=project_service.db_manager,
            tenant_key=current_user.tenant_key,
        )
        default_product = await product_service.get_default_product()
        product_id = str(default_product.id) if default_product else None

    async with project_service.db_manager.get_session_async() as session:
        return await get_used_subseries(
            session,
            current_user.tenant_key,
            type_id,
            series_number,
            exclude_project_id,
            product_id,
        )
