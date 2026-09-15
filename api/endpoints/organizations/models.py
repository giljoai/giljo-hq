# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import datetime

from pydantic import BaseModel, Field




class OrganizationCreate(BaseModel):
    """Schema for creating organization."""

    name: str = Field(..., min_length=1, max_length=255, description="Organization display name")
    slug: str | None = Field(
        None, max_length=100, description="URL-friendly identifier (auto-generated if not provided)"
    )
    settings: dict | None = Field(default_factory=dict, description="Organization-level settings")


class OrganizationUpdate(BaseModel):
    """Schema for updating organization."""

    name: str | None = Field(None, max_length=255, description="Organization display name")
    settings: dict | None = Field(None, description="Organization-level settings")


class MemberResponse(BaseModel):
    """Schema for membership in response."""

    id: str = Field(..., description="Membership ID")
    user_id: str = Field(..., description="User ID")
    role: str = Field(..., description="Member role (owner, admin, member, viewer)")
    joined_at: datetime = Field(..., description="Timestamp when user joined organization")
    invited_by: str | None = Field(None, description="User ID who invited this member")

    class Config:
        from_attributes = True


class OrganizationResponse(BaseModel):
    """Schema for organization response."""

    id: str = Field(..., description="Organization ID")
    name: str = Field(..., description="Organization display name")
    slug: str = Field(..., description="URL-friendly identifier")
    is_active: bool = Field(..., description="Whether organization is active")
    created_at: datetime = Field(..., description="Organization creation timestamp")
    updated_at: datetime | None = Field(None, description="Last update timestamp")
    settings: dict = Field(..., description="Organization-level settings")
    members: list[MemberResponse] = Field(default_factory=list, description="Organization members")

    class Config:
        from_attributes = True




class MemberInvite(BaseModel):
    """Schema for inviting member."""

    user_id: str = Field(..., description="User ID to invite")
    role: str = Field(..., pattern="^(admin|member|viewer)$", description="Role to assign (admin, member, viewer)")


class MemberRoleUpdate(BaseModel):
    """Schema for updating member role."""

    role: str = Field(..., pattern="^(admin|member|viewer)$", description="New role (admin, member, viewer)")


class OwnershipTransfer(BaseModel):
    """Schema for transferring ownership."""

    new_owner_id: str = Field(..., description="User ID of new owner (must be existing member)")
