# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Organization Service - Business logic for organization management.

Handover 0424b: Implements CRUD and membership management.

Features:
- Create organization with owner
- Invite/remove members
- Role management (owner, admin, member, viewer)
- Permission checks

Edition note: this module is [CE] because Organization itself is a shared
model, but ``complete_first_login_setup`` is consumed exclusively by the
SaaS-only wizard at ``api/saas_endpoints/org_setup.py``. The edition
boundary is enforced at the router mount (GILJO_MODE gate in
``api/app.py``), not at module placement.
"""

import logging
import re
import secrets
import string
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    DatabaseError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.organizations import Organization, OrgMembership
from giljo_mcp.repositories.org_repository import OrgRepository
from giljo_mcp.schemas.jsonb_validators import OrganizationSettings
from giljo_mcp.utils.log_sanitizer import sanitize


# Timezone format guard applied at the service boundary. Matches IANA-style
# identifiers ("America/New_York", "Europe/Stockholm", "UTC"), plus the
# historical "Etc/GMT+2" form. Empty string is permitted and treated as "UTC".
_TIMEZONE_ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9/_+\-]+$")
_ORG_NAME_MAX_LENGTH = 100
_TIMEZONE_MAX_LENGTH = 50


logger = logging.getLogger(__name__)


class OrgService:
    """Service for organization management."""

    def __init__(self, session: AsyncSession, websocket_manager: Any | None = None):
        self.session = session
        self._websocket_manager = websocket_manager
        self._repo = OrgRepository()

    # =========================================================================
    # Organization CRUD
    # =========================================================================

    async def create_organization(
        self, name: str, owner_id: str, tenant_key: str, slug: str | None = None, settings: dict | None = None
    ) -> Organization:
        """
        Create organization with owner.

        Args:
            name: Organization display name
            owner_id: User ID who will be owner
            tenant_key: Tenant isolation key
            slug: URL-friendly identifier (auto-generated if not provided)
            settings: Optional org-level settings

        Returns:
            Organization: Created organization with owner membership

        Raises:
            AlreadyExistsError: Organization with slug already exists
            DatabaseError: Database operation failed
        """
        try:
            # Generate slug from name if not provided
            if not slug:
                slug = self._generate_slug(name)

            # Check slug uniqueness
            try:
                existing = await self.get_organization_by_slug(slug)
                if existing:
                    raise AlreadyExistsError(
                        message=f"Organization with slug '{slug}' already exists", context={"slug": slug}
                    )
            except ResourceNotFoundError:
                # Slug is available
                pass

            # Create organization
            org = Organization(name=name, tenant_key=tenant_key, slug=slug, settings=settings or {})
            await self._repo.add_organization(self.session, org)

            # Create owner membership
            owner_membership = OrgMembership(org_id=org.id, user_id=owner_id, tenant_key=tenant_key, role="owner")
            await self._repo.add_membership(self.session, owner_membership)

            await self.session.commit()
            await self._repo.refresh_with_members(self.session, org)

            logger.info(
                "Organization created",
                extra={"org_id": sanitize(org.id), "slug": sanitize(slug), "owner_id": sanitize(owner_id)},
            )

            # Emit WebSocket event (if available)
            if self._websocket_manager:
                await self._websocket_manager.broadcast_to_user(
                    user_id=owner_id, event="org:created", data={"org_id": org.id, "name": name, "slug": slug}
                )

            return org

        except AlreadyExistsError:
            await self._repo.rollback(self.session)
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to create organization")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to create organization", context={"name": name, "slug": slug, "error": str(e)}
            ) from e

    async def get_organization(self, org_id: str, tenant_key: str | None = None) -> Organization:
        """
        Get organization by ID, including soft-deleted orgs in their grace period.

        Soft-deleted orgs (is_active=False, status='deleted') are returned so
        the user can keep using the app during the 30-day account-deletion
        grace window: the existing AccountDeletionBanner / DangerPage UI shows
        the "scheduled for deletion" state with an in-app cancel button, and
        the email cancel link still works. The reaper hard-deletes the row at
        the end of grace, at which point this query naturally returns None
        and login fails because the user row is gone too.

        Args:
            org_id: Organization ID
            tenant_key: Tenant isolation key. When provided the lookup is
                tenant-scoped — a row in another tenant returns
                ResourceNotFoundError, not the foreign row. Pass this
                whenever the caller is acting on behalf of a specific user.

        Returns:
            Organization: Found organization with members (may be soft-deleted)

        Raises:
            ResourceNotFoundError: Organization row does not exist (purged or
                never existed)
            DatabaseError: Database operation failed
        """
        try:
            org = await self._repo.get_organization_by_id(
                self.session, org_id, tenant_key=tenant_key, active_only=False
            )

            if not org:
                raise ResourceNotFoundError(
                    message="Organization not found",
                    context={"org_id": org_id, "tenant_key": tenant_key},
                )

            return org

        except ResourceNotFoundError:
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to get organization")
            raise DatabaseError(
                message="Failed to get organization", context={"org_id": org_id, "error": str(e)}
            ) from e

    async def get_organization_by_slug(self, slug: str) -> Organization:
        """
        Get organization by slug.

        Args:
            slug: Organization slug

        Returns:
            Organization: Found organization with members

        Raises:
            ResourceNotFoundError: Organization with slug not found
            DatabaseError: Database operation failed
        """
        try:
            org = await self._repo.get_organization_by_slug(self.session, slug)

            if not org:
                raise ResourceNotFoundError(message="Organization not found", context={"slug": slug})

            return org

        except ResourceNotFoundError:
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to get organization by slug")
            raise DatabaseError(
                message="Failed to get organization by slug", context={"slug": slug, "error": str(e)}
            ) from e

    async def update_organization(
        self, org_id: str, name: str | None = None, settings: dict | None = None
    ) -> Organization:
        """
        Update organization details.

        Args:
            org_id: Organization ID
            name: New organization name
            settings: New organization settings

        Returns:
            Organization: Updated organization

        Raises:
            ResourceNotFoundError: Organization not found
            DatabaseError: Database operation failed
        """
        try:
            org = await self.get_organization(org_id)

            if name:
                org.name = name
            if settings is not None:
                org.settings = settings

            await self.session.commit()

            logger.info("Organization updated", extra={"org_id": sanitize(org_id)})

            # Re-query with members to ensure relationships are loaded
            return await self.get_organization(org_id)

        except ResourceNotFoundError:
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to update organization")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to update organization", context={"org_id": org_id, "error": str(e)}
            ) from e

    async def complete_first_login_setup(
        self,
        org_id: str,
        tenant_key: str,
        org_name: str,
        timezone_name: str = "UTC",
    ) -> Organization:
        """
        Complete the first-login org setup wizard.

        Atomic write path that mutates an organization row created at
        registration: updates display name, regenerates a unique slug,
        merges ``timezone`` into the ``settings`` JSONB (preserving
        existing keys), and flips ``org_setup_complete`` to ``True``.

        This is the single authoritative write entry for the org-setup
        wizard. The endpoint MUST route through this method — no direct
        setattr against the ORM from the router layer.

        Args:
            org_id: Organization UUID to mutate. Looked up with tenant_key.
            tenant_key: Caller's tenant key. Required for tenant isolation.
            org_name: Cleaned organization display name.
            timezone_name: IANA timezone identifier (default "UTC").

        Returns:
            Organization: Refreshed organization with members loaded.

        Raises:
            ValidationError: Name or timezone failed validation.
            ResourceNotFoundError: Org not found for this tenant_key.
            DatabaseError: Persistence failure.
        """
        # --- Input validation (untrusted boundary -> clean 422 upstream) ---
        clean_name = (org_name or "").strip()
        if len(clean_name) < 2:
            raise ValidationError(
                message="Organization name must be at least 2 non-whitespace characters.",
                context={"org_name_len": len(clean_name)},
            )
        if len(clean_name) > _ORG_NAME_MAX_LENGTH:
            raise ValidationError(
                message=f"Organization name exceeds {_ORG_NAME_MAX_LENGTH} characters.",
                context={"org_name_len": len(clean_name)},
            )

        clean_tz = (timezone_name or "UTC").strip() or "UTC"
        if len(clean_tz) > _TIMEZONE_MAX_LENGTH:
            raise ValidationError(
                message=f"Timezone exceeds {_TIMEZONE_MAX_LENGTH} characters.",
                context={"timezone_len": len(clean_tz)},
            )
        if not _TIMEZONE_ALLOWED_PATTERN.match(clean_tz):
            raise ValidationError(
                message="Invalid timezone format.",
                context={"timezone": clean_tz},
            )

        try:
            # --- Tenant-scoped lookup (enforces isolation at the repo) ---
            org = await self._repo.get_organization_by_id(self.session, org_id, tenant_key=tenant_key)
            if org is None:
                raise ResourceNotFoundError(
                    message="Organization not found",
                    context={"org_id": org_id, "tenant_key": tenant_key},
                )

            # --- Slug regeneration with cross-tenant uniqueness guard ---
            candidate_slug = self._generate_slug(clean_name)
            if await self._repo.slug_taken_by_other_org(self.session, candidate_slug, exclude_org_id=org.id):
                suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
                candidate_slug = f"{candidate_slug}-{suffix}"

            # --- Settings JSONB merge (validate; preserve existing keys) ---
            current_settings = dict(org.settings) if org.settings else {}
            current_settings["timezone"] = clean_tz
            # Validate at the service boundary — raises on invalid input.
            # Pydantic with extra="allow" would round-trip the dict intact,
            # but we keep the merged dict itself to avoid any risk of dropping
            # dynamic keys not declared on OrganizationSettings.
            OrganizationSettings.model_validate(current_settings)
            merged_settings = dict(current_settings)

            # --- Field-allowlist write (mirrors post-0962 discipline) ---
            # Two attempts: the slug check above cannot be atomic with the
            # write, so anything it cannot see (a racing setup) can still trip
            # the global idx_org_slug unique index. On that one violation,
            # roll back, re-read the row and retry once with a random suffix
            # rather than surfacing a 500 to a first-login user. Nothing else
            # is pending in this transaction — the wizard write is
            # self-contained — so a plain rollback discards only this attempt.
            for attempt in (1, 2):
                org.name = clean_name
                org.slug = candidate_slug
                org.settings = merged_settings
                org.org_setup_complete = True
                try:
                    await self.session.commit()
                    break
                except IntegrityError as integrity_exc:
                    if attempt == 2 or "idx_org_slug" not in str(integrity_exc.orig):
                        raise
                    await self._repo.rollback(self.session)
                    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
                    candidate_slug = f"{self._generate_slug(clean_name)}-{suffix}"
                    org = await self._repo.get_organization_by_id(self.session, org_id, tenant_key=tenant_key)
                    if org is None:
                        raise ResourceNotFoundError(
                            message="Organization not found",
                            context={"org_id": org_id, "tenant_key": tenant_key},
                        ) from integrity_exc

            logger.info(
                "Org first-login setup complete",
                extra={
                    "org_id": org.id,
                    "tenant_key": tenant_key,
                    "slug": candidate_slug,
                },
            )

            # Re-fetch tenant-scoped with members loaded for the response.
            refreshed = await self._repo.get_organization_by_id(self.session, org.id, tenant_key=tenant_key)
            return refreshed or org

        except ResourceNotFoundError:
            # Read-only pre-mutation path: nothing to roll back, and calling
            # session.rollback() here corrupts the ambient test transaction
            # used by integration fixtures. Preserve the session state.
            raise
        except (ValidationError, AlreadyExistsError):
            await self._repo.rollback(self.session)
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to complete first-login org setup")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to complete first-login org setup",
                context={"org_id": org_id, "error": str(e)},
            ) from e

    async def delete_organization(self, org_id: str) -> None:
        """
        Delete organization (soft delete by setting is_active=False).

        Args:
            org_id: Organization ID

        Raises:
            ResourceNotFoundError: Organization not found
            DatabaseError: Database operation failed
        """
        try:
            org = await self.get_organization(org_id)
            org.is_active = False

            await self.session.commit()

            logger.info("Organization deleted (soft)", extra={"org_id": sanitize(org_id)})

        except ResourceNotFoundError:
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to delete organization")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to delete organization", context={"org_id": org_id, "error": str(e)}
            ) from e

    # =========================================================================
    # Membership Management
    # =========================================================================

    async def invite_member(
        self, org_id: str, user_id: str, role: str, invited_by: str, tenant_key: str
    ) -> OrgMembership:
        """
        Invite user to organization.

        Args:
            org_id: Organization ID
            user_id: User ID to invite
            role: Role to assign (admin, member, viewer)
            invited_by: User ID of inviter
            tenant_key: Tenant isolation key

        Returns:
            OrgMembership: Created membership

        Raises:
            AlreadyExistsError: User is already a member
            ValidationError: Invalid role specified
            DatabaseError: Database operation failed
        """
        try:
            # Check if already a member
            existing = await self._get_membership(org_id, user_id)
            if existing:
                raise AlreadyExistsError(
                    message="User is already a member of this organization",
                    context={"org_id": org_id, "user_id": user_id},
                )

            # Validate role
            if role not in ("admin", "member", "viewer"):
                raise ValidationError(
                    message=f"Invalid role: {role}. Must be admin, member, or viewer",
                    context={"role": role, "valid_roles": ["admin", "member", "viewer"]},
                )

            membership = OrgMembership(
                org_id=org_id, user_id=user_id, role=role, invited_by=invited_by, tenant_key=tenant_key
            )
            await self._repo.add_membership(self.session, membership)
            await self.session.commit()

            logger.info(
                "Member invited to organization",
                extra={
                    "org_id": sanitize(org_id),
                    "user_id": sanitize(user_id),
                    "role": sanitize(role),
                    "invited_by": sanitize(invited_by),
                },
            )

            # Emit WebSocket event (if available)
            if self._websocket_manager:
                await self._websocket_manager.broadcast_to_user(
                    user_id=user_id, event="org:invited", data={"org_id": org_id, "role": role}
                )

            return membership

        except (AlreadyExistsError, ValidationError):
            await self._repo.rollback(self.session)
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to invite member")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to invite member", context={"org_id": org_id, "user_id": user_id, "error": str(e)}
            ) from e

    async def remove_member(self, org_id: str, user_id: str) -> None:
        """
        Remove member from organization.

        Args:
            org_id: Organization ID
            user_id: User ID to remove

        Raises:
            ResourceNotFoundError: User is not a member
            AuthorizationError: Cannot remove owner (must transfer first)
            DatabaseError: Database operation failed
        """
        try:
            membership = await self._get_membership(org_id, user_id)

            if not membership:
                raise ResourceNotFoundError(
                    message="User is not a member", context={"org_id": org_id, "user_id": user_id}
                )

            if membership.role == "owner":
                raise AuthorizationError(
                    message="Cannot remove owner. Transfer ownership first.",
                    context={"org_id": org_id, "user_id": user_id, "role": "owner"},
                )

            await self._repo.delete_membership(self.session, membership)
            await self.session.commit()

            logger.info(
                "Member removed from organization",
                extra={"org_id": sanitize(org_id), "user_id": sanitize(user_id)},
            )

        except (ResourceNotFoundError, AuthorizationError):
            await self._repo.rollback(self.session)
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to remove member")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to remove member", context={"org_id": org_id, "user_id": user_id, "error": str(e)}
            ) from e

    async def change_member_role(self, org_id: str, user_id: str, new_role: str) -> OrgMembership:
        """
        Change member's role in organization.

        Args:
            org_id: Organization ID
            user_id: User ID whose role to change
            new_role: New role to assign

        Returns:
            OrgMembership: Updated membership

        Raises:
            ResourceNotFoundError: User is not a member
            AuthorizationError: Cannot change owner role (must use transfer_ownership)
            ValidationError: Invalid role specified
            DatabaseError: Database operation failed
        """
        try:
            membership = await self._get_membership(org_id, user_id)

            if not membership:
                raise ResourceNotFoundError(
                    message="User is not a member", context={"org_id": org_id, "user_id": user_id}
                )

            if membership.role == "owner":
                raise AuthorizationError(
                    message="Cannot change owner role. Use transfer_ownership instead.",
                    context={"org_id": org_id, "user_id": user_id, "role": "owner"},
                )

            if new_role not in ("admin", "member", "viewer"):
                raise ValidationError(
                    message=f"Invalid role: {new_role}",
                    context={"new_role": new_role, "valid_roles": ["admin", "member", "viewer"]},
                )

            membership.role = new_role
            await self.session.commit()

            logger.info(
                "Member role changed",
                extra={"org_id": sanitize(org_id), "user_id": sanitize(user_id), "new_role": sanitize(new_role)},
            )

            return membership

        except (ResourceNotFoundError, AuthorizationError, ValidationError):
            await self._repo.rollback(self.session)
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to change member role")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to change member role", context={"org_id": org_id, "user_id": user_id, "error": str(e)}
            ) from e

    async def transfer_ownership(self, org_id: str, current_owner_id: str, new_owner_id: str) -> None:
        """
        Transfer organization ownership to another member.

        Args:
            org_id: Organization ID
            current_owner_id: Current owner's user ID
            new_owner_id: New owner's user ID

        Raises:
            AuthorizationError: Current user is not owner
            ResourceNotFoundError: New owner is not a member
            DatabaseError: Database operation failed
        """
        try:
            # Verify current owner
            current = await self._get_membership(org_id, current_owner_id)
            if not current or current.role != "owner":
                raise AuthorizationError(
                    message="Only owner can transfer ownership", context={"org_id": org_id, "user_id": current_owner_id}
                )

            # Verify new owner is a member
            new_owner = await self._get_membership(org_id, new_owner_id)
            if not new_owner:
                raise ResourceNotFoundError(
                    message="New owner must be a member", context={"org_id": org_id, "user_id": new_owner_id}
                )

            # Transfer
            current.role = "admin"  # Demote to admin
            new_owner.role = "owner"

            await self.session.commit()

            logger.info(
                "Ownership transferred",
                extra={
                    "org_id": sanitize(org_id),
                    "from": sanitize(current_owner_id),
                    "to": sanitize(new_owner_id),
                },
            )

        except (AuthorizationError, ResourceNotFoundError):
            await self._repo.rollback(self.session)
            raise
        except SQLAlchemyError as e:
            logger.exception("Failed to transfer ownership")
            await self._repo.rollback(self.session)
            raise DatabaseError(
                message="Failed to transfer ownership",
                context={"org_id": org_id, "from": current_owner_id, "to": new_owner_id, "error": str(e)},
            ) from e

    async def list_members(self, org_id: str) -> list[OrgMembership]:
        """
        List all members of organization.

        Args:
            org_id: Organization ID

        Returns:
            list[OrgMembership]: List of active memberships

        Raises:
            DatabaseError: Database operation failed
        """
        try:
            return await self._repo.list_members(self.session, org_id)

        except SQLAlchemyError as e:
            logger.exception("Failed to list members")
            raise DatabaseError(message="Failed to list members", context={"org_id": org_id, "error": str(e)}) from e

    # =========================================================================
    # User Queries
    # =========================================================================

    async def get_user_organizations(self, user_id: str) -> list[Organization]:
        """
        Get all organizations for a user.

        Args:
            user_id: User ID

        Returns:
            list[Organization]: List of organizations user is a member of

        Raises:
            DatabaseError: Database operation failed
        """
        try:
            return await self._repo.get_user_organizations(self.session, user_id)

        except SQLAlchemyError as e:
            logger.exception("Failed to get user organizations")
            raise DatabaseError(
                message="Failed to get user organizations", context={"user_id": user_id, "error": str(e)}
            ) from e

    async def get_user_role(self, org_id: str, user_id: str) -> str | None:
        """Get user's role in organization."""
        membership = await self._get_membership(org_id, user_id)
        return membership.role if membership else None

    # =========================================================================
    # Permission Checks
    # =========================================================================

    async def can_manage_members(self, org_id: str, user_id: str) -> bool:
        """Check if user can manage members (owner or admin)."""
        role = await self.get_user_role(org_id, user_id)
        return role in ("owner", "admin")

    async def can_edit_org(self, org_id: str, user_id: str) -> bool:
        """Check if user can edit organization (owner or admin)."""
        role = await self.get_user_role(org_id, user_id)
        return role in ("owner", "admin")

    async def can_delete_org(self, org_id: str, user_id: str) -> bool:
        """Check if user can delete organization (owner only)."""
        role = await self.get_user_role(org_id, user_id)
        return role == "owner"

    async def can_view_org(self, org_id: str, user_id: str) -> bool:
        """Check if user can view organization (any member)."""
        role = await self.get_user_role(org_id, user_id)
        return role is not None

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _get_membership(self, org_id: str, user_id: str) -> OrgMembership | None:
        """Get membership for user in org."""
        return await self._repo.get_membership(self.session, org_id, user_id)

    def _generate_slug(self, name: str) -> str:
        """Generate URL-friendly slug from name."""
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)  # Remove special chars
        slug = re.sub(r"[\s_-]+", "-", slug)  # Replace spaces with hyphens
        return slug.strip("-")
