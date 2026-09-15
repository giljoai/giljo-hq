# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models.auth import User
from giljo_mcp.services.org_service import OrgService
from giljo_mcp.utils.log_sanitizer import sanitize

from .models import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)


logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize_organization(org) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "is_active": org.is_active,
        "created_at": org.created_at,
        "updated_at": org.updated_at,
        "settings": org.settings or {},
        "members": [
            {"id": m.id, "user_id": m.user_id, "role": m.role, "joined_at": m.joined_at, "invited_by": m.invited_by}
            for m in (org.members or [])
        ],
    }


def get_org_service(db: AsyncSession = Depends(get_db_session)) -> OrgService:
    return OrgService(db)


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    org_data: OrganizationCreate,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Create new organization with current user as owner.

    Args:
        org_data: Organization creation data
        current_user: Current authenticated user (becomes owner)
        org_service: Organization service instance

    Returns:
        Created organization with owner membership

    Raises:
        AlreadyExistsError: Organization with slug already exists (409)
        DatabaseError: Database operation failed (500)
    """
    org = await org_service.create_organization(
        name=org_data.name,
        slug=org_data.slug,
        owner_id=current_user.id,
        tenant_key=current_user.tenant_key,
        settings=org_data.settings,
    )

    logger.info("Organization created via API", extra={"org_id": org.id, "slug": org.slug, "owner_id": current_user.id})

    return _serialize_organization(org)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: User = Depends(get_current_active_user), org_service: OrgService = Depends(get_org_service)
):
    """
    List all organizations for current user.

    Returns organizations where current user is a member (any role).

    Args:
        current_user: Current authenticated user
        org_service: Organization service instance

    Returns:
        List of organizations user belongs to

    Raises:
        DatabaseError: Database operation failed (500)
    """
    orgs = await org_service.get_user_organizations(current_user.id)
    return [_serialize_organization(org) for org in orgs]


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Get organization by ID.

    Requires user's org_id to match OR to be a member of the organization.

    Args:
        org_id: Organization ID
        current_user: Current authenticated user
        org_service: Organization service instance

    Returns:
        Organization details with members

    Raises:
        AuthorizationError: User is not a member of organization (403)
        ResourceNotFoundError: Organization not found (404)
        DatabaseError: Database operation failed (500)
    """
    logger.debug(
        "Organization access check",
        extra={
            "org_id": sanitize(org_id),
            "user_id": sanitize(current_user.id),
            "user_org_id": sanitize(str(current_user.org_id)),
            "org_id_match": str(current_user.org_id) == str(org_id),
        },
    )

    if str(current_user.org_id) != str(org_id) and not await org_service.can_view_org(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")

    org = await org_service.get_organization(org_id)
    return _serialize_organization(org)


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    org_data: OrganizationUpdate,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Update organization (owner or admin only).

    Allows updating organization name and settings.
    Requires owner or admin role.

    Args:
        org_id: Organization ID
        org_data: Update data
        current_user: Current authenticated user
        org_service: Organization service instance

    Returns:
        Updated organization

    Raises:
        AuthorizationError: User is not owner or admin (403)
        ResourceNotFoundError: Organization not found (404)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_edit_org(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can update organization")

    org = await org_service.update_organization(org_id=org_id, name=org_data.name, settings=org_data.settings)

    logger.info(
        "Organization updated via API",
        extra={"org_id": sanitize(org_id), "updated_by": sanitize(current_user.id)},
    )

    return _serialize_organization(org)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Delete organization (owner only).

    Soft deletes organization by setting is_active=False.
    Only organization owner can delete.

    Args:
        org_id: Organization ID
        current_user: Current authenticated user
        org_service: Organization service instance

    Raises:
        AuthorizationError: User is not owner (403)
        ResourceNotFoundError: Organization not found (404)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_delete_org(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can delete organization")

    await org_service.delete_organization(org_id)

    logger.info(
        "Organization deleted via API",
        extra={"org_id": sanitize(org_id), "deleted_by": sanitize(current_user.id)},
    )
