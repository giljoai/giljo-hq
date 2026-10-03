# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.auth import User
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_product_memory_service
from .models import MemoryEntriesResponse, MemoryEntryResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{product_id}/memory-entries", response_model=MemoryEntriesResponse)
async def get_memory_entries(
    product_id: str,
    project_id: str | None = Query(None, description="Filter by specific project"),
    limit: int = Query(10, ge=1, le=100, description="Maximum entries to return (1-100)"),
    search: str | None = Query(
        None,
        max_length=200,
        description="Optional full-text search over summary, project, outcomes, decisions, and tags",
    ),
    current_user: User = Depends(get_current_active_user),
    memory_service: ProductMemoryService = Depends(get_product_memory_service),
) -> MemoryEntriesResponse:
    """
    Get 360 memory entries for a product.

    Fetches memory entries from the normalized product_memory_entries table.
    Entries are product-scoped but linked to projects for traceability.

    Query Parameters:
        project_id: Optional UUID to filter entries by specific project
        limit: Maximum number of entries to return (default: 10, max: 100)
        search: Optional full-text search term (max 200 chars). When present,
            entries are filtered + relevance-ranked server-side.

    Returns:
        MemoryEntriesResponse with entries array and counts

    Raises:
        404: Product not found or not accessible to tenant
        422: Invalid UUID format, or search term over the length cap
    """
    try:
        UUID(product_id)
        project_uuid_str = None
        if project_id:
            UUID(project_id)
            project_uuid_str = project_id
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail="Invalid UUID format.",
        ) from e

    search_query = search.strip() if search else None
    if not search_query:
        search_query = None

    try:
        result = await memory_service.get_memory_entries(
            product_id=product_id,
            project_id=project_uuid_str,
            limit=limit,
            search_query=search_query,
        )
    except ResourceNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Product {product_id} not found or not accessible",
        ) from None

    entries = result["entries"]
    total_count = result["total_count"]

    entry_responses = []
    for entry in entries:
        entry_dict = entry.to_dict()
        entry_responses.append(
            MemoryEntryResponse(
                id=entry_dict["id"],
                sequence=entry_dict["sequence"],
                entry_type=entry_dict["type"],
                source=entry_dict["source"],
                timestamp=entry_dict["timestamp"],
                project_id=entry_dict["project_id"],
                project_name=entry_dict["project_name"],
                summary=entry_dict["summary"],
                key_outcomes=entry_dict["key_outcomes"],
                decisions_made=entry_dict["decisions_made"],
                git_commits=entry_dict["git_commits"],
                deliverables=entry_dict["deliverables"],
                metrics=entry_dict["metrics"],
                priority=entry_dict["priority"],
                significance_score=entry_dict["significance_score"],
                tags=entry_dict["tags"],
                author_job_id=entry_dict["author_job_id"],
                author_name=entry_dict["author_name"],
                author_type=entry_dict["author_type"],
                deleted_by_user=entry_dict["deleted_by_user"],
            )
        )

    logger.info(
        f"Fetched {len(entry_responses)} memory entries for product {sanitize(product_id)}",
        extra={
            "tenant_key": sanitize(current_user.tenant_key),
            "product_id": sanitize(product_id),
            "project_id": sanitize(project_id),
            "limit": sanitize(limit),
            "filtered_count": len(entry_responses),
        },
    )

    return MemoryEntriesResponse(
        success=True,
        entries=entry_responses,
        total_count=total_count,
        filtered_count=len(entry_responses),
    )
