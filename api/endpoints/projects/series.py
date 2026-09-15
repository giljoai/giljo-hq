# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
