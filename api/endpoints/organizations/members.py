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

from .models import MemberInvite, MemberResponse, MemberRoleUpdate, OwnershipTransfer


logger = logging.getLogger(__name__)

router = APIRouter()


def get_org_service(db: AsyncSession = Depends(get_db_session)) -> OrgService:
    return OrgService(db)


@router.get("/{org_id}/members", response_model=list[MemberResponse])
async def list_members(
    org_id: str,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    List all members of organization.

    Requires user to be a member of the organization.

    Args:
        org_id: Organization ID
        current_user: Current authenticated user
        org_service: Organization service instance

    Returns:
        List of organization members with roles

    Raises:
        AuthorizationError: User is not a member (403)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_view_org(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")

    return await org_service.list_members(org_id)


@router.post("/{org_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    org_id: str,
    invite_data: MemberInvite,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Invite user to organization (owner or admin only).

    Creates membership record for invited user.
    Requires owner or admin role.

    Args:
        org_id: Organization ID
        invite_data: Invitation data (user_id, role)
        current_user: Current authenticated user
        org_service: Organization service instance

    Returns:
        Created membership record

    Raises:
        AuthorizationError: User is not owner or admin (403)
        AlreadyExistsError: User is already a member (409)
        ValidationError: Invalid role specified (400)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_manage_members(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can invite members")

    membership = await org_service.invite_member(
        org_id=org_id,
        user_id=invite_data.user_id,
        role=invite_data.role,
        invited_by=current_user.id,
        tenant_key=current_user.tenant_key,
    )

    logger.info(
        "Member invited via API",
        extra={
            "org_id": sanitize(org_id),
            "invited_user_id": sanitize(invite_data.user_id),
            "role": sanitize(invite_data.role),
            "invited_by": sanitize(current_user.id),
        },
    )

    return membership


@router.put("/{org_id}/members/{user_id}", response_model=MemberResponse)
async def change_member_role(
    org_id: str,
    user_id: str,
    role_data: MemberRoleUpdate,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Change member's role (owner or admin only).

    Updates member's role within organization.
    Requires owner or admin role.
    Cannot change owner's role.

    Args:
        org_id: Organization ID
        user_id: User ID whose role to change
        role_data: New role data
        current_user: Current authenticated user
        org_service: Organization service instance

    Returns:
        Updated membership record

    Raises:
        AuthorizationError: User is not owner/admin or trying to change owner role (403)
        ResourceNotFoundError: User is not a member (404)
        ValidationError: Invalid role specified (400)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_manage_members(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can change member roles")

    membership = await org_service.change_member_role(org_id=org_id, user_id=user_id, new_role=role_data.role)

    logger.info(
        "Member role changed via API",
        extra={
            "org_id": sanitize(org_id),
            "user_id": sanitize(user_id),
            "new_role": sanitize(role_data.role),
            "changed_by": sanitize(current_user.id),
        },
    )

    return membership


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: str,
    user_id: str,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Remove member from organization (owner or admin only).

    Deletes membership record.
    Requires owner or admin role.
    Cannot remove organization owner.

    Args:
        org_id: Organization ID
        user_id: User ID to remove
        current_user: Current authenticated user
        org_service: Organization service instance

    Raises:
        AuthorizationError: User is not owner/admin or trying to remove owner (403)
        ResourceNotFoundError: User is not a member (404)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_manage_members(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can remove members")

    await org_service.remove_member(org_id=org_id, user_id=user_id)

    logger.info(
        "Member removed via API",
        extra={
            "org_id": sanitize(org_id),
            "removed_user_id": sanitize(user_id),
            "removed_by": sanitize(current_user.id),
        },
    )


transfer_router = APIRouter()


@transfer_router.post("/{org_id}/transfer")
async def transfer_ownership(
    org_id: str,
    transfer_data: OwnershipTransfer,
    current_user: User = Depends(get_current_active_user),
    org_service: OrgService = Depends(get_org_service),
):
    """
    Transfer organization ownership (owner only).

    Changes organization owner to another member.
    Previous owner becomes admin.
    Only current owner can transfer ownership.

    Args:
        org_id: Organization ID
        transfer_data: Transfer data (new_owner_id)
        current_user: Current authenticated user (must be owner)
        org_service: Organization service instance

    Returns:
        Success message

    Raises:
        AuthorizationError: User is not owner (403)
        ResourceNotFoundError: New owner is not a member (404)
        DatabaseError: Database operation failed (500)
    """
    if not await org_service.can_delete_org(org_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can transfer ownership")

    await org_service.transfer_ownership(
        org_id=org_id, current_owner_id=current_user.id, new_owner_id=transfer_data.new_owner_id
    )

    logger.info(
        "Ownership transferred via API",
        extra={
            "org_id": sanitize(org_id),
            "previous_owner_id": sanitize(current_user.id),
            "new_owner_id": sanitize(transfer_data.new_owner_id),
        },
    )

    return {"message": "Ownership transferred"}
