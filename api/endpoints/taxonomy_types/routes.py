# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.services.taxonomy_ops import (
    create_taxonomy_type,
    delete_taxonomy_type,
    ensure_default_types_seeded,
    get_project_count_for_type,
    list_taxonomy_types,
    update_taxonomy_type,
)

from .schemas import TaxonomyTypeCreate, TaxonomyTypeResponse, TaxonomyTypeUpdate


logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(tt: Any, project_count: int) -> TaxonomyTypeResponse:
    return TaxonomyTypeResponse(
        id=str(tt.id),
        tenant_key=tt.tenant_key,
        abbreviation=tt.abbreviation,
        label=tt.label,
        color=tt.color,
        sort_order=tt.sort_order,
        project_count=project_count,
        created_at=tt.created_at,
        updated_at=tt.updated_at,
    )


@router.get("/", response_model=list[TaxonomyTypeResponse])
async def list_types(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> list[TaxonomyTypeResponse]:
    """List all taxonomy types for the current tenant.

    Triggers lazy seeding of default types on first access.
    """
    tenant_key = current_user.tenant_key

    await ensure_default_types_seeded(session, tenant_key)

    types = await list_taxonomy_types(session, tenant_key)
    return [_to_response(tt, tt.project_count) for tt in types]


@router.post("/", response_model=TaxonomyTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_type(
    data: TaxonomyTypeCreate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> TaxonomyTypeResponse:
    """Create a custom taxonomy type."""
    tenant_key = current_user.tenant_key

    try:
        tt = await create_taxonomy_type(
            session,
            tenant_key,
            abbreviation=data.abbreviation,
            label=data.label,
            color=data.color,
            sort_order=data.sort_order,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Taxonomy type already exists.") from None

    return _to_response(tt, 0)


@router.put("/{type_id}", response_model=TaxonomyTypeResponse)
async def update_type(
    type_id: str,
    data: TaxonomyTypeUpdate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> TaxonomyTypeResponse:
    """Update a taxonomy type (label, color, sort_order only)."""
    tenant_key = current_user.tenant_key

    try:
        update_fields = data.model_dump(exclude_unset=True)
        tt = await update_taxonomy_type(session, tenant_key, type_id, **update_fields)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taxonomy type not found.") from None

    count = await get_project_count_for_type(session, tenant_key, type_id)

    return _to_response(tt, count)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_type(
    type_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a taxonomy type (fails if projects are assigned)."""
    tenant_key = current_user.tenant_key

    try:
        await delete_taxonomy_type(session, tenant_key, type_id)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg) from None
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg) from None
