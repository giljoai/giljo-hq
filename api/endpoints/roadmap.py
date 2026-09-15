# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.endpoints.dependencies import get_roadmap_service
from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.models import User
from giljo_mcp.models.roadmaps import MAX_ROADMAP_SORT_ORDER
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()


class RoadmapReorderItem(BaseModel):
    """One {id, sort_order} pair in a reorder request."""

    id: str = Field(..., min_length=1, description="roadmap_item id")
    sort_order: int = Field(..., ge=0, le=MAX_ROADMAP_SORT_ORDER, description="New order index within the roadmap")


class RoadmapReorderRequest(BaseModel):
    """Bulk reorder payload. Out-of-range priorities are rejected with 422."""

    items: list[RoadmapReorderItem]


@router.get("")
async def get_roadmap(
    current_user: User = Depends(get_current_active_user),
    roadmap_service: RoadmapService = Depends(get_roadmap_service),
) -> dict[str, Any]:
    """Return the active product's roadmap + items joined to display fields.

    404 if no product is active. When a product is active but has no roadmap
    yet, returns ``{product_id, roadmap: null, items: []}``.
    """
    logger.debug("User %s fetching roadmap", sanitize(current_user.username))
    return await roadmap_service.get_roadmap(tenant_key=current_user.tenant_key)


@router.patch("/reorder")
async def reorder_roadmap(
    payload: RoadmapReorderRequest,
    current_user: User = Depends(get_current_active_user),
    roadmap_service: RoadmapService = Depends(get_roadmap_service),
) -> dict[str, Any]:
    """Bulk sort_order update for the active product's roadmap items.

    Only items belonging to the active product's roadmap are updated; unknown /
    cross-tenant ids are silently skipped (the returned count reflects what was
    actually changed).
    """
    logger.debug("User %s reordering roadmap (%d items)", sanitize(current_user.username), len(payload.items))
    updates = [item.model_dump() for item in payload.items]
    return await roadmap_service.reorder(updates=updates, tenant_key=current_user.tenant_key)


@router.delete("/items/{item_id}")
async def remove_roadmap_item(
    item_id: str,
    current_user: User = Depends(get_current_active_user),
    roadmap_service: RoadmapService = Depends(get_roadmap_service),
) -> dict[str, Any]:
    """Remove one item from the active product's roadmap (tenant + product scoped).

    Deletes ONLY the roadmap_item, never the underlying project/task. An item_id
    that is not in the caller's active-product roadmap (another tenant's, a
    different product's, or unknown) is a clean no-op (``removed=0``), never a
    500. 404 only when no product is active.
    """
    logger.debug("User %s removing roadmap item %s", sanitize(current_user.username), sanitize(item_id))
    return await roadmap_service.remove_item(item_id=item_id, tenant_key=current_user.tenant_key)
