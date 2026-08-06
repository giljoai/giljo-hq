# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
User Management API endpoints.

Provides REST API for comprehensive user CRUD operations:
- List all users (admin only, filtered by tenant)
- Create new user (admin only)
- Get user details (admin or self)
- Update user profile (admin or self)
- Soft-delete user (admin only)
- Change user role (admin only)
- Change password (self or admin)
- Field Toggle Configuration (Handover 0048, 0820):
  - GET /me/field-priority: Get user's toggle config or defaults
  - PUT /me/field-priority: Update user's field toggle config
  - POST /me/field-priority/reset: Reset to system defaults

All endpoints enforce role-based access control and multi-tenant isolation.
"""

import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints.auth_models import BoundedPassword
from api.endpoints.dependencies import get_db_manager, get_user_service
from giljo_mcp.auth.dependencies import (
    enforce_sensitive_account_field_guard,
    get_current_active_user,
    get_db_session,
    require_admin,
)
from giljo_mcp.models import User
from giljo_mcp.services import UserService
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()


class UserCreate(BaseModel):
    """Request model for creating a new user"""

    username: str = Field(..., min_length=3, max_length=64, description="Unique username")
    email: EmailStr | None = Field(None, description="User email address")
    first_name: str | None = Field(None, min_length=1, max_length=255, description="Given name")
    last_name: str | None = Field(None, max_length=255, description="Family name (optional)")
    password: BoundedPassword = Field(..., description="User password (min 8 characters)")
    role: str = Field("developer", description="User role: admin, developer, viewer")
    is_active: bool = Field(default=True, description="Whether user account is active")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate role is one of allowed values"""
        allowed_roles = ["admin", "developer", "viewer"]
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of: {', '.join(allowed_roles)}")
        return v


class UserUpdate(BaseModel):
    """Request model for updating user profile"""

    username: str | None = Field(None, min_length=3, max_length=64)
    email: EmailStr | None = None
    first_name: str | None = Field(None, min_length=1, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    password: BoundedPassword | None = Field(None, description="New password (min 8 chars)")
    recovery_pin: str | None = Field(
        None, min_length=4, max_length=4, pattern="^[0-9]{4}$", description="4-digit recovery PIN"
    )


class UserResponse(BaseModel):
    """Response model for user data (password excluded)"""

    id: str
    username: str
    email: str | None
    first_name: str | None = None
    last_name: str | None = None
    # full_name retained for one release as a derived/legacy display field.
    full_name: str | None
    role: str
    tenant_key: str
    is_active: bool
    created_at: str
    last_login: str | None


class PasswordChange(BaseModel):
    """Request model for password change"""

    old_password: str | None = Field(None, min_length=8, description="Current password (required for non-admin)")
    new_password: BoundedPassword = Field(..., description="New password (min 8 characters)")


class RoleChange(BaseModel):
    """Request model for role change"""

    role: str = Field(..., description="New role: admin, developer, viewer")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate role is one of allowed values"""
        allowed_roles = ["admin", "developer", "viewer"]
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of: {', '.join(allowed_roles)}")
        return v


class RoleChangeResponse(BaseModel):
    """Response model for role change"""

    message: str
    user_id: str
    username: str
    role: str


class ForceLogoutResponse(BaseModel):
    """Response model for an admin force-logout (SEC-6011)."""

    message: str
    user_id: str
    username: str
    token_revocation_epoch: int


class PasswordChangeResponse(BaseModel):
    """Response model for password change"""

    message: str


class FieldPriorityConfig(BaseModel):
    """
    Request/Response model for field toggle configuration v3.0.

    Handover 0820: Toggle-only system (removed priority integers).
    Each category is either enabled (true) or disabled (false).

    Valid categories: product_core, vision_documents, agent_templates,
                     project_description, memory_360, git_history,
                     tech_stack, architecture, testing
    """

    priorities: dict[str, Any] = Field(
        ..., description="Category toggle config. Values: {'toggle': true/false} or flat bool"
    )
    version: str = Field("3.0", description="Config schema version")

    @field_validator("priorities")
    @classmethod
    def validate_toggle_values(cls, v: dict[str, Any]) -> dict[str, Any]:
        """
        Validate toggle configuration.

        Rules:
        1. Toggle values must be boolean (or dict with 'toggle' key)
        2. Valid categories only
        3. At least one category must be enabled
        """
        valid_categories = {
            "product_core",
            "vision_documents",
            "agent_templates",
            "project_description",
            "memory_360",
            "git_history",
            "tech_stack",
            "architecture",
            "testing",
        }

        # Validate category names
        invalid_categories = set(v.keys()) - valid_categories
        if invalid_categories:
            raise ValueError(f"Invalid category names: {invalid_categories}. Valid categories: {valid_categories}")

        # Validate toggle values and check at least one enabled
        has_enabled = False
        for category, value in v.items():
            if isinstance(value, dict):
                if "toggle" not in value or not isinstance(value["toggle"], bool):
                    raise ValueError(
                        f"Invalid toggle config for '{category}'. Must be {{'toggle': true/false}} or a flat boolean"
                    )
                if value["toggle"]:
                    has_enabled = True
            elif isinstance(value, bool):
                if value:
                    has_enabled = True
            else:
                raise ValueError(  # noqa: TRY004  Pydantic validators must raise ValueError
                    f"Invalid value for '{category}': {value}. Must be {{'toggle': true/false}} or a flat boolean"
                )

        # product_core and project_description are always-on and never sent
        # in the payload, so all toggleable categories being disabled is valid
        always_on = {"product_core", "project_description"}
        has_always_on = bool(always_on & set(v.keys()))
        if not has_enabled and has_always_on:
            raise ValueError("At least one category must be enabled")

        return v


class DepthConfig(BaseModel):
    """
    Depth configuration for context extraction granularity (Handovers 0314, 0347d, 0347e).

    Controls HOW MUCH detail to extract from each context source.
    Orthogonal to priority system (which controls WHAT to fetch).

    Valid values per field:
    - vision_documents: none, optional, light, medium, full (0347e)
    - memory_last_n_projects: 1, 3, 5, 10
    - git_commits: 10, 25, 50, 100
    - agent_templates: basic, full (0347d)
    - tech_stack_sections: required, all
    - architecture_depth: overview, detailed (stored, NOT applied -- see field description)
    """

    vision_documents: Literal["none", "optional", "light", "medium", "full"] = Field(
        default="medium", description="Vision document depth level: none/optional/light/medium/full (Handover 0347e)"
    )
    memory_last_n_projects: Literal[1, 3, 5, 10] = Field(
        default=3, description="Number of recent projects to include in 360 memory"
    )
    git_commits: Literal[5, 10, 25, 50, 100] = Field(default=25, description="Number of recent git commits to include")
    agent_templates: Literal["basic", "full"] = Field(
        default="basic",
        description="get_context roster detail: basic (name/role/desc) / full (+instructions). Not agent identity.",
    )
    tech_stack_sections: Literal["required", "all"] = Field(default="all", description="Tech stack sections to include")
    architecture_depth: Literal["overview", "detailed"] = Field(
        default="overview",
        description="Architecture depth. STORED BUT NOT APPLIED - get_architecture takes no depth param.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vision_documents": "medium",
                "memory_last_n_projects": 3,
                "git_commits": 25,
                "agent_templates": "basic",
                "tech_stack_sections": "all",
                "architecture_depth": "overview",
            }
        }
    )


class UpdateDepthConfigRequest(BaseModel):
    """Request to update user depth configuration."""

    depth_config: DepthConfig


# Helper Functions


def user_to_response(user: User) -> UserResponse:
    """Convert User model to UserResponse (excludes password)"""
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        role=user.role,
        tenant_key=user.tenant_key,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login=user.last_login.isoformat() if user.last_login else None,
    )


# API Endpoints


# TENANT-LEVEL
@router.get("/", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(require_admin), user_service: UserService = Depends(get_user_service)
) -> list[UserResponse]:
    """
    List users within the current admin's tenant.

    Requires admin role. Returns only users whose ``tenant_key`` matches the admin's
    tenant. Cross-tenant user administration is an ops-panel concern (INF-0002), not a
    product concern — mode (CE/demo/SaaS) and role are orthogonal (SEC-0005a).

    Args:
        current_user: Current authenticated admin user
        user_service: User service for database operations

    Returns:
        List of UserResponse objects (passwords excluded)

    Raises:
        HTTPException: 400 if current user has no tenant_key
        AuthorizationError: User is not admin (403)
        BaseGiljoError: Database operation failed (500)
    """
    if not current_user.tenant_key:
        logger.error("Admin %s has null/empty tenant_key — refusing to list users", sanitize(current_user.username))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user has no tenant_key; cannot scope user list.",
        )

    logger.debug(
        "Admin %s listing users in tenant %s",
        sanitize(current_user.username),
        sanitize(current_user.tenant_key),
    )

    # Tenant-scoped: admin sees only users in their own tenant (SEC-0005a)
    users = await user_service.list_users(tenant_key=current_user.tenant_key)

    logger.info("Found %d users in tenant %s", len(users), sanitize(current_user.tenant_key))

    # 0731d: UserService returns list[User] ORM objects - use attribute access
    return [user_to_response(user) for user in users]


# TENANT-LEVEL
@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
) -> UserResponse:
    """
    Create a new user.

    Requires admin role. New user inherits tenant_key from admin.

    Args:
        user_data: User creation data
        current_user: Current authenticated admin user
        user_service: User service for database operations

    Returns:
        Created user data (password excluded)

    Raises:
        ValidationError: Username or email already exists (400)
        AuthorizationError: User is not admin (403)
        BaseGiljoError: Database operation failed (500)
    """
    # IMP-5042: adding ADDITIONAL users (multi-seat) is gated to editions that
    # support it. No shipping edition does today — CE is single-user (self-hosted
    # license) and SaaS Solo is single-seat — so this returns 403, matching the
    # hidden "Add User" button in the dashboard. It re-opens automatically for the
    # future SaaS Team tier via member_management_enabled(). This is the second of
    # two admin user-creation surfaces (the other is POST /api/auth/register);
    # both gate on the same edition policy. The gate lives at this boundary so
    # UserService.create_user stays a capability-agnostic mechanism reused by
    # bootstrap, provisioning, and tests.
    from api.app_state import member_management_enabled

    if not member_management_enabled():
        logger.info(
            "Blocked create_user by %s — multi-user administration not available on this edition",
            sanitize(current_user.username),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Adding additional users isn't available on this plan.",
        )

    logger.debug("Admin %s creating user: %s", sanitize(current_user.username), sanitize(user_data.username))

    # SEC (v1.1.9.2): pass the admin-supplied password through. The historical
    # `password=None` here silently dropped the validated UserCreate.password and
    # caused every user created via the admin UI to be hashed against the literal
    # "GiljoMCP". Pydantic UserCreate already enforces min_length=8 — no extra
    # validation needed here. UserService.create_user raises ValidationError on
    # missing/empty password as defense-in-depth.
    user = await user_service.create_user(
        username=user_data.username,
        email=user_data.email,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        password=user_data.password,
        role=user_data.role,
        is_active=user_data.is_active,
    )

    logger.info(
        "Created user: %s (role: %s) in tenant %s",
        sanitize(user_data.username),
        sanitize(user_data.role),
        sanitize(current_user.tenant_key),
    )

    # 0731d: UserService returns User ORM object - use helper
    return user_to_response(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> UserResponse:
    """
    Get user details by ID.

    Admin can view any user across all tenants (per-user tenancy design).
    Non-admin can only view themselves.

    Args:
        user_id: UUID of user to retrieve
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        User data (password excluded)

    Raises:
        AuthorizationError: Non-admin tries to view other users (403)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)
    """
    logger.debug("User %s retrieving user %s", sanitize(current_user.username), sanitize(str(user_id)))

    # Tenant-scoped lookup: admins can manage users only within their own tenant (SEC-0005a)
    is_admin = current_user.role == "admin"
    user = await user_service.get_user(str(user_id))

    # 0731d: UserService returns User ORM object - use attribute access
    # Authorization: admin can view any user in tenant, non-admin can only view self
    if not is_admin and str(user.id) != str(current_user.id):
        logger.warning("Non-admin %s tried to view user %s", sanitize(current_user.username), sanitize(user.username))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view other users' profiles")

    return user_to_response(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> UserResponse:
    """
    Update user profile.

    Admin can update any user in their tenant. Non-admin can only update themselves.

    Args:
        user_id: UUID of user to update
        user_data: Fields to update
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        Updated user data (password excluded)

    Raises:
        ValidationError: Email already exists (400)
        AuthorizationError: Non-admin tries to update other users (403)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)
    """
    logger.debug("User %s updating user %s", sanitize(current_user.username), sanitize(str(user_id)))

    # SEC-9170: a leaked API key / OAuth Bearer must not mutate account-security
    # fields (password/email/is_active/recovery_pin); require a browser session.
    # recovery_pin is additionally refused in hosted SaaS (CE-only boundary).
    enforce_sensitive_account_field_guard(request, user_data)

    # Tenant-scoped update: admins can manage users only within their own tenant (SEC-0005a)
    is_admin = current_user.role == "admin"

    # Authorization: admin can update any user in tenant, non-admin can only update self
    user = await user_service.get_user(str(user_id))

    # 0731d: UserService returns User ORM object - use attribute access
    if not is_admin and str(user.id) != str(current_user.id):
        logger.warning("Non-admin %s tried to update user %s", sanitize(current_user.username), sanitize(user.username))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update other users' profiles")

    # Build updates dict (only include non-None values)
    updates = {}
    if user_data.username is not None:
        updates["username"] = user_data.username
    if user_data.email is not None:
        updates["email"] = user_data.email
    if user_data.first_name is not None:
        updates["first_name"] = user_data.first_name
    if user_data.last_name is not None:
        updates["last_name"] = user_data.last_name
    if user_data.is_active is not None:
        updates["is_active"] = user_data.is_active
    if user_data.password is not None:
        updates["password"] = user_data.password

    # PIN write routes through UserService (tenant-scoped, single-field allowlist) — BE-6003
    if user_data.recovery_pin is not None:
        await user_service.set_recovery_pin(str(user_id), user_data.recovery_pin)

    updated_user = await user_service.update_user(str(user_id), **updates)

    logger.info("Updated user: %s", sanitize(user.username))

    return user_to_response(updated_user)


# TENANT-LEVEL
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
) -> None:
    """
    Soft-delete user by deactivating account.

    Requires admin role. Sets is_active=False instead of hard deletion for audit trail.

    Args:
        user_id: UUID of user to deactivate
        current_user: Current authenticated admin user
        user_service: User service for database operations

    Raises:
        AuthorizationError: User is not admin (403)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)
    """
    logger.debug("Admin %s deactivating user %s", sanitize(current_user.username), sanitize(str(user_id)))

    await user_service.delete_user(str(user_id))

    logger.info("Deactivated user: %s", sanitize(str(user_id)))


# TENANT-LEVEL
@router.put("/{user_id}/role", response_model=RoleChangeResponse)
async def change_user_role(
    user_id: UUID,
    role_data: RoleChange,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
) -> RoleChangeResponse:
    """
    Change user role.

    Requires admin role. Admin cannot change their own role (prevent lockout).

    Args:
        user_id: UUID of user to change role
        role_data: New role data
        current_user: Current authenticated admin user
        user_service: User service for database operations

    Returns:
        Role change confirmation with new role

    Raises:
        ValidationError: Admin tries to change their own role or invalid role (400)
        AuthorizationError: User is not admin or cannot demote last admin (403)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)
    """
    logger.debug(
        f"Admin {sanitize(current_user.username)} changing role for user {sanitize(user_id)} to {sanitize(role_data.role)}"
    )

    # Prevent self-demotion (admin cannot change their own role)
    if str(user_id) == str(current_user.id):
        logger.warning(f"Admin {current_user.username} tried to change their own role")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role (prevents lockout)",
        )

    # 0731d: UserService returns User ORM object - use attribute access
    user = await user_service.auth.change_role(str(user_id), role_data.role)

    logger.info(f"Changed role for user {user.username} to {user.role}")

    return RoleChangeResponse(
        message="User role updated successfully",
        user_id=str(user.id),
        username=user.username,
        role=user.role,
    )


@router.post("/{user_id}/force-logout", response_model=ForceLogoutResponse)
async def force_logout_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
) -> ForceLogoutResponse:
    """Force-log-out a user (SEC-6011 admin-forced-logout).

    Requires admin role. Bumps the target user's forced-logout epoch so EVERY
    access token they currently hold is rejected on its next request; a fresh
    login mints a token at the new epoch and works normally. Tenant-scoped — an
    admin can only force-log-out users in their own tenant.

    Self-targeting is permitted (it invalidates the admin's own outstanding
    tokens too); the admin simply re-logs in.

    Args:
        user_id: UUID of the user to force-log-out.
        current_user: Current authenticated admin user.
        user_service: User service for database operations.

    Returns:
        Confirmation with the user's new revocation epoch.

    Raises:
        AuthorizationError: Caller is not an admin (403).
        ResourceNotFoundError: User not found in this tenant (404).
        BaseGiljoError: Database operation failed (500).
    """
    logger.info(f"Admin {sanitize(current_user.username)} force-logging-out user {sanitize(user_id)}")

    user = await user_service.auth.force_logout(str(user_id))

    return ForceLogoutResponse(
        message="User forced-logged-out successfully",
        user_id=str(user.id),
        username=user.username,
        token_revocation_epoch=user.token_revocation_epoch,
    )


@router.put("/{user_id}/password", response_model=PasswordChangeResponse)
async def change_password(
    user_id: UUID,
    password_data: PasswordChange,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
    db: AsyncSession = Depends(get_db_session),
) -> PasswordChangeResponse:
    """
    Change user password.

    Users can change their own password (requires old password verification).
    Admin can change any user's password (no old password required).

    Args:
        user_id: UUID of user to change password
        password_data: Password change data
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        Password change confirmation

    Raises:
        ValidationError: Old password not provided (400)
        AuthenticationError: Old password incorrect (401)
        AuthorizationError: Non-admin tries to change other users' passwords (403)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)
    """
    logger.debug(f"User {sanitize(current_user.username)} changing password for user {sanitize(user_id)}")

    # Authorization: admin can change any password, non-admin can only change own
    if current_user.role != "admin" and str(user_id) != str(current_user.id):
        logger.warning(
            f"Non-admin {sanitize(current_user.username)} tried to change password for user {sanitize(user_id)}"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change other users' passwords")

    # Determine if admin is bypassing old password check
    is_admin = current_user.role == "admin" and str(user_id) != str(current_user.id)

    await user_service.auth.change_password(
        str(user_id),
        old_password=password_data.old_password,
        new_password=password_data.new_password,
        is_admin=is_admin,
    )

    # SEC-6001: a password change must invalidate the session that performed it.
    # Revoke the requester's presented access token by jti so the old cookie
    # cannot continue to authenticate after the credential changed. Admin
    # changing ANOTHER user's password cannot revoke that user's tokens by jti
    # (no token in hand) — those roll off at expiry; this closes the
    # self-service path, which is the common case.
    if str(user_id) == str(current_user.id):
        access_token = request.cookies.get("access_token")
        if access_token:
            from giljo_mcp.services.oauth_revocation_service import revoke_dashboard_access_jwt

            await revoke_dashboard_access_jwt(db, token=access_token)

    logger.info(f"Password changed for user: {sanitize(user_id)}")
    return PasswordChangeResponse(message="Password changed successfully")


# Field Toggle Configuration Endpoints (Handover 0048, 0820)


@router.get("/me/field-priority", response_model=FieldPriorityConfig)
async def get_field_priority_config(
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> FieldPriorityConfig:
    """
    Get user's field toggle configuration or defaults (v3.0).

    Returns the authenticated user's custom field toggle configuration if set,
    otherwise returns the system default v3.0 configuration.

    Handover 0820: Toggle-only system (removed priority integers).

    Args:
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        FieldPriorityConfig: User's custom config or system defaults (v3.0)

    Raises:
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)

    Example Response (v3.0):
        {
            "version": "3.0",
            "priorities": {
                "product_core": {"toggle": true},
                "agent_templates": {"toggle": true},
                "vision_documents": {"toggle": true},
                "git_history": {"toggle": false}
            }
        }
    """
    logger.debug(f"User {current_user.username} retrieving field toggle config")

    config = await user_service.get_field_priority_config(str(current_user.id))

    logger.debug(f"Returning field toggle config for user {current_user.username}")
    return FieldPriorityConfig(**config)


@router.put("/me/field-priority", response_model=FieldPriorityConfig)
async def update_field_priority_config(
    config: FieldPriorityConfig,
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
    db: AsyncSession = Depends(get_db_session),
) -> FieldPriorityConfig:
    """
    Update user's field toggle configuration (v3.0).

    Validates category names and toggle values before saving. Emits WebSocket
    event for real-time UI synchronization across clients.

    Rejects git_history=true when system-level git_integration is disabled (422).

    Handover 0820: Toggle-only system (removed priority integers).

    Args:
        config: New field toggle configuration (v3.0)
        current_user: Current authenticated user
        user_service: User service for database operations
        db: Database session for settings lookup

    Returns:
        FieldPriorityConfig: Updated configuration

    Raises:
        HTTPException 422: git_history=true but git_integration is disabled
        ValidationError: Invalid toggle or category (400/422)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)
    """
    logger.debug(
        f"User {sanitize(current_user.username)} updating field toggle config to v{sanitize(config.version)}",
        extra={
            "user_id": sanitize(str(current_user.id)),
            "tenant_key": sanitize(current_user.tenant_key),
            "config_version": sanitize(config.version),
        },
    )

    # Validate: git_history cannot be enabled when git_integration is disabled
    git_history_entry = config.priorities.get("git_history")
    if git_history_entry:
        wants_git_history = (
            git_history_entry.get("toggle", False) if isinstance(git_history_entry, dict) else bool(git_history_entry)
        )
        if wants_git_history:
            settings_service = SettingsService(db, current_user.tenant_key)
            git_settings = await settings_service.get_setting_value("integrations", "git_integration", {})
            if not git_settings.get("enabled", False):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Cannot enable git_history when system-level git integration is disabled. "
                    "Enable git integration first via Settings > Integrations.",
                )

    # Pydantic validation already enforced (toggle booleans, valid categories, at least one enabled)
    await user_service.update_field_priority_config(str(current_user.id), config.model_dump())

    logger.info(
        f"Updated field toggle config for user: {sanitize(current_user.username)}",
        extra={
            "user_id": sanitize(str(current_user.id)),
            "tenant_key": sanitize(current_user.tenant_key),
            "toggles": sanitize(config.priorities),
        },
    )

    return config


@router.post("/me/field-priority/reset", response_model=FieldPriorityConfig)
async def reset_field_priority_config(
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> FieldPriorityConfig:
    """
    Reset field toggle configuration to system defaults.

    Clears user's custom configuration and returns system defaults (v3.0).
    Useful for reverting customizations.

    Args:
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        FieldPriorityConfig: System default configuration (v3.0)

    Raises:
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)

    Example Response:
        {
            "version": "3.0",
            "priorities": {
                "product_core": {"toggle": true},
                "agent_templates": {"toggle": true},
                ...
            }
        }
    """
    logger.debug(f"User {current_user.username} resetting field toggle config to defaults")

    await user_service.reset_field_priority_config(str(current_user.id))

    logger.info(f"Reset field toggle config to defaults for user: {current_user.username}")

    # Return defaults by re-reading from service (which returns defaults when no rows exist)
    config = await user_service.get_field_priority_config(str(current_user.id))
    return FieldPriorityConfig(**config)


# Depth Configuration Endpoints (Handover 0314)


@router.get("/me/context/depth", response_model=dict[str, Any])
async def get_depth_config(
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> dict[str, Any]:
    """
    Get user's depth configuration.

    Returns the authenticated user's depth configuration (or defaults).

    Handover 0314: Context Management v2.0 - Depth Controls
    - Controls HOW MUCH detail to extract from each context source
    - Orthogonal to priority system (which controls WHAT to fetch)

    Args:
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        Dict with depth_config field

    Raises:
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)

    Example Response:
        {
            "depth_config": {
                "vision_documents": "medium",
                "memory_last_n_projects": 3,
                "git_commits": 25,
                "agent_templates": "basic",
                "tech_stack_sections": "all",
                "architecture_depth": "overview"
            }
        }
    """
    logger.debug(f"User {current_user.username} retrieving depth config")

    config = await user_service.get_depth_config(str(current_user.id))

    logger.debug(f"Returning depth config for user {current_user.username}")

    return {"depth_config": config}


@router.put("/me/context/depth", response_model=dict[str, Any])
async def update_depth_config(
    depth_request: UpdateDepthConfigRequest,
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> dict[str, Any]:
    """
    Update user's depth configuration.

    Validates depth settings via Pydantic schema and saves to database.
    Emits WebSocket event for real-time UI synchronization.

    Handover 0314: Context Management v2.0 - Depth Controls

    Args:
        depth_request: New depth configuration
        current_user: Current authenticated user
        user_service: User service for database operations

    Returns:
        Dict with updated depth_config

    Raises:
        ValidationError: Invalid depth values (400/422)
        ResourceNotFoundError: User not found (404)
        BaseGiljoError: Database operation failed (500)

    Example Request:
        {
            "depth_config": {
                "vision_documents": "full",
                "memory_last_n_projects": 5,
                "git_commits": 50,
                "agent_templates": "full",
                "tech_stack_sections": "all",
                "architecture_depth": "detailed"
            }
        }
    """
    logger.debug(
        f"User {current_user.username} updating depth config",
        extra={"user_id": str(current_user.id), "tenant_key": current_user.tenant_key},
    )

    # BE-9322: every DepthConfig field has a default, so a plain model_dump()
    # turned a partial body into a six-key overwrite. The service already
    # merges per key; exclude_unset is what makes the merge reach it.
    await user_service.update_depth_config(
        str(current_user.id), depth_request.depth_config.model_dump(exclude_unset=True)
    )

    logger.info(
        f"Updated depth config for user: {current_user.username}",
        extra={"user_id": str(current_user.id), "tenant_key": current_user.tenant_key},
    )

    # Get updated config from service
    config = await user_service.get_depth_config(str(current_user.id))

    return {"depth_config": config}


# ---------------------------------------------------------------------------
# Notification preferences (Handover 0831)
# ---------------------------------------------------------------------------


@router.get("/me/settings/notification-preferences")
async def get_notification_preferences(
    current_user: User = Depends(get_current_active_user),
    db_manager=Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Get the current user's notification preferences.

    Returns default preferences if not yet customized.
    """
    from giljo_mcp.config.defaults import DEFAULT_NOTIFICATION_PREFERENCES

    prefs = current_user.notification_preferences or DEFAULT_NOTIFICATION_PREFERENCES
    return {"notification_preferences": prefs}


@router.put("/me/settings/notification-preferences")
async def update_notification_preferences(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_active_user),
    user_service: UserService = Depends(get_user_service),
) -> dict[str, Any]:
    """
    Update the current user's notification preferences.

    Sprint 003c: Write routed through UserService (no direct session.commit).

    Supported fields:
    - context_tuning_reminder: bool (default: true)
    - tuning_reminder_threshold: int (minimum 3, default: 10)
    """
    prefs = await user_service.update_notification_preferences(
        user_id=current_user.id,
        payload=payload,
    )

    return {"notification_preferences": prefs}
