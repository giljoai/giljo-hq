# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
AuthService - Authentication and authorization service layer.

Handover 0322 Phase 2: Service Layer Compliance
Handover 0480b: Exception-based error handling (migrated from dict returns)
Handover 0731c: Typed service returns (AuthResult, SetupStateInfo, ApiKeyInfo,
    ApiKeyCreateResult, UserInfo) replacing dict[str, Any].
Implements production-grade authentication operations following TDD discipline.

Responsibilities:
- User authentication (login validation, JWT token generation)
- Last login timestamp management
- Setup state checking
- API key management (list, create, revoke)
- User registration (admin + first admin flows)

Design Principles:
- NO tenant_key in constructor (auth operates across tenants for login)
- Dependency Injection: Accepts DatabaseManager
- Async/Await: Full SQLAlchemy 2.0 async support
- Error Handling: Raises typed exceptions (AuthenticationError, ValidationError, etc.)
- Typed Returns: All public methods return Pydantic models, not raw dicts
- Testability: Can be unit tested independently
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession


if TYPE_CHECKING:
    from giljo_mcp.services.notification_service import NotificationService

from giljo_mcp.api_key_utils import bust_api_key_cache, generate_api_key, get_key_prefix, hash_api_key
from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.models.config import SetupState
from giljo_mcp.repositories.auth_repository import AuthRepository
from giljo_mcp.schemas.service_responses import (
    ApiKeyCreateResult,
    ApiKeyInfo,
    AuthResult,
    SetupStateInfo,
    UserInfo,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.utils.log_sanitizer import sanitize
from giljo_mcp.utils.password_helper import DUMMY_BCRYPT_HASH, async_hash_password, async_verify_password


logger = logging.getLogger(__name__)


class AuthService:
    """
    Service for managing authentication and authorization operations.

    This service handles all auth-related operations including:
    - User authentication (login with username/password)
    - JWT token generation for authenticated sessions
    - Last login timestamp updates
    - Setup state checking (first admin created, etc.)
    - API key management (list, create, revoke)
    - User registration (admin creates users, first admin creation)

    Thread Safety: Each instance is request-scoped. Do not share across requests.
    NO tenant_key: Auth operations span tenants (login can be any tenant).
    """

    def __init__(self, db_manager: DatabaseManager, websocket_manager=None, session: AsyncSession | None = None):
        """
        Initialize AuthService with database manager.

        Args:
            db_manager: Database manager for async database operations
            websocket_manager: Optional WebSocket manager for event emission
            session: Optional AsyncSession for test transaction isolation (Handover 0324)
        """
        self.db_manager = db_manager
        self._websocket_manager = websocket_manager
        self._session = session  # Store for test transaction isolation
        self._repo = AuthRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
        """
        Get a session, preferring an injected test session when provided.
        This keeps service methods compatible with test transaction fixtures.

        Returns:
            Context manager for database session
        """
        if self._session is not None:

            @asynccontextmanager
            async def _test_session_wrapper():
                if tenant_key:
                    self._session.info["tenant_key"] = tenant_key
                yield self._session

            return _test_session_wrapper()

        if tenant_key:

            @asynccontextmanager
            async def _tenant_session_wrapper():
                async with self.db_manager.get_session_async() as session:
                    session.info["tenant_key"] = tenant_key
                    yield session

            return _tenant_session_wrapper()
        return self.db_manager.get_session_async()

    # ============================================================================
    # Authentication Methods
    # ============================================================================

    async def authenticate_user(self, username: str, password: str) -> AuthResult:
        """
        Authenticate user and return AuthResult with user profile and JWT token.

        Args:
            username: Username to authenticate
            password: Plaintext password to verify

        Returns:
            AuthResult with user_id, username, token, tenant_key, role, and
            optional profile fields (email, full_name, is_active, etc.)

        Raises:
            AuthenticationError: If credentials are invalid
            AuthorizationError: If user account is inactive
            BaseGiljoError: For other errors

        Example:
            >>> result = await service.authenticate_user("admin", "Password123!")
            >>> token = result.token
        """
        try:
            # BE-6068 F1: look the user up inside the session, then RELEASE the
            # pooled connection before the bcrypt verify. bcrypt.checkpw is
            # ~250-400ms of pure CPU; running it off the event loop
            # (asyncio.to_thread, in _authenticate_user_impl) AND outside the
            # open session keeps it from freezing the loop or pinning a DB
            # connection for the duration. expire_on_commit=False keeps the
            # detached user's columns readable after the block exits.
            #
            # AUTH-EMAIL dual-lookup (handover af53e62b): the ``username``
            # parameter is an opaque identifier — username lookup first, email
            # lookup (case-insensitive) on miss; a generic AuthenticationError is
            # raised for both misses (no leakage of which lookup failed).
            async with self._get_session() as session:
                user = await self._repo.get_user_by_username(session, username)
                if user is None:
                    user = await self._repo.get_user_by_email(session, username)

            return await self._authenticate_user_impl(user, username, password)

        except (AuthenticationError, AuthorizationError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to authenticate user")
            raise BaseGiljoError(message=f"Authentication failed: {e!s}", context={"identifier": username}) from e

    async def _authenticate_user_impl(self, user: User | None, username: str, password: str) -> AuthResult:
        """Verify the already-fetched ``user``'s password and build the AuthResult.

        The caller fetches ``user`` inside a DB session and releases the pooled
        connection before invoking this method, so the bcrypt verify below runs
        off both the event loop and the DB connection (BE-6068 F1). The
        wire-level ``username`` parameter name is preserved for API compatibility
        and reused for error context/logging.
        """
        # One bcrypt verify on EVERY path, off the event loop, so response time
        # can't reveal whether the account exists (SEC-9217c timing oracle): the
        # real stored hash when present, else DUMMY_BCRYPT_HASH whose result is
        # discarded via the `stored is not None` gate. BE-1004 amendment 4: a
        # social-only user (password_hash IS NULL) must fail the SAME generic
        # way as a wrong password, never crash on a None hash.
        stored = user.password_hash if user is not None else None
        password_ok = await async_verify_password(password, stored or DUMMY_BCRYPT_HASH) and stored is not None

        if not password_ok:
            self._logger.warning(
                f"Authentication failed for identifier: {sanitize(username)}",
                extra={"identifier": sanitize(username), "reason": "invalid_credentials"},
            )
            raise AuthenticationError(message="Invalid credentials", context={"identifier": username})

        # Check if user account is active
        if not user.is_active:
            self._logger.warning(
                f"Authentication failed for identifier: {sanitize(username)} (inactive account)",
                extra={"identifier": sanitize(username), "user_id": sanitize(user.id), "reason": "inactive_account"},
            )
            raise AuthorizationError(
                message="User account is inactive", context={"identifier": username, "user_id": user.id}
            )

        # Generate JWT token
        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            tenant_key=user.tenant_key,
            revocation_epoch=user.token_revocation_epoch or 0,
        )

        self._logger.info(
            f"User authenticated successfully: {sanitize(username)}",
            extra={"username": sanitize(username), "user_id": sanitize(user.id), "role": sanitize(user.role)},
        )

        return AuthResult(
            user_id=str(user.id),
            username=user.username,
            token=token,
            tenant_key=user.tenant_key,
            role=user.role,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            full_name=user.full_name,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else None,
            last_login=user.last_login.isoformat() if user.last_login else None,
        )

    async def find_user_for_lockout_notice(self, identifier: str) -> dict | None:
        """Pre-auth lookup for the SEC-3001a Wave 2 item-6 lockout email notice.

        Resolves the submitted login identifier (username, then email) to a real
        user and returns ONLY the primitives a notifier needs — never the ORM
        object — so the caller can publish a neutral, edition-safe event. Returns
        ``None`` when the identifier matches no user (so an attacker locking a
        non-existent identifier triggers no notification and leaks nothing).

        Best-effort: never raises (a notification lookup must not break login).
        """
        try:
            async with self._get_session() as session:
                user = await self._repo.get_user_by_username(session, identifier)
                if user is None:
                    user = await self._repo.get_user_by_email(session, identifier)
                if user is None or not user.email:
                    return None
                return {
                    "email": user.email,
                    "user_id": str(user.id),
                    "tenant_key": user.tenant_key,
                }
        except Exception:  # noqa: BLE001 - notification lookup is best-effort
            self._logger.warning("find_user_for_lockout_notice failed", exc_info=True)
            return None

    async def update_last_login(self, user_id: str, timestamp: datetime) -> None:
        """
        Update user's last login timestamp.

        Args:
            user_id: User UUID
            timestamp: Login timestamp (UTC)

        Raises:
            ResourceNotFoundError: If user not found
            BaseGiljoError: For other errors

        Example:
            >>> await service.update_last_login(user_id, datetime.now(timezone.utc))
        """
        try:
            async with self._get_session() as session:
                await self._update_last_login_impl(session, user_id, timestamp)

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to update last login")
            raise BaseGiljoError(message=f"Failed to update last login: {e!s}", context={"user_id": user_id}) from e

    async def _update_last_login_impl(self, session: AsyncSession, user_id: str, timestamp: datetime) -> None:
        """Implementation that uses provided session."""
        user = await self._repo.get_user_by_id(session, user_id)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        await self._repo.update_last_login(session, user, timestamp)

        self._logger.debug(
            f"Updated last login for user {user_id}", extra={"user_id": user_id, "timestamp": timestamp.isoformat()}
        )

    # ============================================================================
    # Setup State Methods
    # ============================================================================

    async def check_setup_state(self, tenant_key: str) -> SetupStateInfo | None:
        """
        Check setup state for tenant.

        Args:
            tenant_key: Tenant key

        Returns:
            SetupStateInfo with first_admin_created, database_initialized,
            and tenant_key fields, or None if no setup state exists.

        Raises:
            BaseGiljoError: For errors

        Example:
            >>> state = await service.check_setup_state("test_tenant")
            >>> if state and state.first_admin_created:
            ...     print("Admin exists")
        """
        try:
            async with self._get_session(tenant_key) as session:
                return await self._check_setup_state_impl(session, tenant_key)

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to check setup state")
            raise BaseGiljoError(
                message=f"Failed to check setup state: {e!s}", context={"tenant_key": tenant_key}
            ) from e

    async def _check_setup_state_impl(self, session: AsyncSession, tenant_key: str) -> SetupStateInfo | None:
        """Implementation that uses provided session."""
        setup_state = await self._repo.get_setup_state(session, tenant_key)

        if not setup_state:
            return None

        return SetupStateInfo(
            first_admin_created=setup_state.first_admin_created,
            database_initialized=setup_state.database_initialized,
            tenant_key=setup_state.tenant_key,
        )

    # ============================================================================
    # API Key Methods
    # ============================================================================

    async def list_api_keys(self, user_id: str, include_revoked: bool = False) -> list[ApiKeyInfo]:
        """
        List API keys for user.

        Args:
            user_id: User UUID
            include_revoked: Include revoked keys in results (default: False)

        Returns:
            List of ApiKeyInfo models (never contains raw keys or hashes)

        Raises:
            BaseGiljoError: For errors

        Example:
            >>> keys = await service.list_api_keys(user_id, include_revoked=True)
            >>> for key in keys:
            ...     print(key.name, key.is_active)
        """
        try:
            async with self._get_session() as session:
                return await self._list_api_keys_impl(session, user_id, include_revoked)

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list API keys")
            raise BaseGiljoError(message=f"Failed to list API keys: {e!s}", context={"user_id": user_id}) from e

    async def _list_api_keys_impl(self, session: AsyncSession, user_id: str, include_revoked: bool) -> list[ApiKeyInfo]:
        """Implementation that uses provided session."""
        tenant_key = await self._tenant_key_for_user(session, user_id, allow_missing=True)
        if tenant_key is None:
            return []
        session.info["tenant_key"] = tenant_key
        api_keys = await self._repo.list_api_keys(session, user_id, tenant_key, include_revoked)

        return [
            ApiKeyInfo(
                id=str(key.id),
                name=key.name,
                key_prefix=key.key_prefix,
                permissions=key.permissions or [],
                is_active=key.is_active,
                created_at=key.created_at.isoformat() if key.created_at else None,
                last_used=key.last_used.isoformat() if key.last_used else None,
                revoked_at=key.revoked_at.isoformat() if key.revoked_at else None,
                expires_at=key.expires_at.isoformat() if key.expires_at else None,
            )
            for key in api_keys
        ]

    async def create_api_key(
        self,
        user_id: str,
        tenant_key: str,
        name: str,
        permissions: list[str],
        *,
        replaces_key_id: str | None = None,
        notification_service: "NotificationService | None" = None,
    ) -> ApiKeyCreateResult:
        """
        Create new API key for user.

        Args:
            user_id: User UUID
            tenant_key: Tenant key
            name: API key name/description
            permissions: List of permissions (e.g., ["*"] for all)
            replaces_key_id: Optional prior key id this new key replaces. When
                set with ``notification_service``, the prior key's
                ``api_key.expiring_soon`` notification is resolved (auto-clear).
            notification_service: Owning service for the notifications table,
                used to resolve the replaced key's expiry notification.

        Returns:
            ApiKeyCreateResult containing the raw API key (shown only once),
            key_prefix for identification, and key_hash for storage.

        Raises:
            BaseGiljoError: For errors

        Example:
            >>> result = await service.create_api_key(user_id, tenant_key, "My Key", ["*"])
            >>> print("Store this key:", result.api_key)
        """
        try:
            async with self._get_session(tenant_key) as session:
                result = await self._create_api_key_impl(session, user_id, tenant_key, name, permissions)

        except BaseGiljoError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to create API key")
            raise BaseGiljoError(
                message=f"Failed to create API key: {e!s}", context={"user_id": user_id, "name": name}
            ) from e

        if replaces_key_id and notification_service is not None:
            await notification_service.resolve_by_dedupe_key(tenant_key, f"api_key.expiring_soon:{replaces_key_id}")

        return result

    async def _create_api_key_impl(
        self, session: AsyncSession, user_id: str, tenant_key: str, name: str, permissions: list[str]
    ) -> ApiKeyCreateResult:
        """Implementation that uses provided session."""
        # BE-6147: the previous hard cap of 5 active API keys per user was removed
        # (product directive — unlimited). Natural sprawl control remains: keys
        # are 90-day-expiring (``expires_at`` below) and individually revocable.
        # Teams-readiness (ADR-009): keys stay scoped by tenant_key + user_id.

        # Generate new API key
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        key_prefix = get_key_prefix(api_key, length=12)

        # Validate permissions JSONB before persisting
        from giljo_mcp.schemas.jsonb_validators import validate_api_key_permissions

        validated_permissions = validate_api_key_permissions(permissions) or []

        # Create API key record
        new_key = APIKey(
            id=str(uuid4()),
            user_id=user_id,
            tenant_key=tenant_key,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            permissions=validated_permissions,
            is_active=True,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )

        new_key = await self._repo.create_api_key(session, new_key)

        self._logger.info(
            f"API key created: {sanitize(name)} (user: {sanitize(user_id)})",
            extra={"user_id": sanitize(user_id), "key_name": sanitize(name), "key_prefix": sanitize(key_prefix)},
        )

        return ApiKeyCreateResult(
            id=str(new_key.id),
            name=new_key.name,
            api_key=api_key,  # RAW KEY - only shown once!
            key_prefix=key_prefix,
            key_hash=key_hash,
            permissions=new_key.permissions,
            expires_at=new_key.expires_at.isoformat() if new_key.expires_at else None,
        )

    async def revoke_api_key(
        self,
        key_id: str,
        user_id: str,
        *,
        notification_service: "NotificationService | None" = None,
    ) -> None:
        """
        Revoke (deactivate) an API key.

        Args:
            key_id: API key UUID
            user_id: User UUID (for ownership verification)
            notification_service: Owning service for the notifications table.
                When provided, the revoked key's ``api_key.expiring_soon``
                notification is resolved (auto-clear).

        Raises:
            ResourceNotFoundError: If API key not found or access denied
            BaseGiljoError: For other errors

        Example:
            >>> await service.revoke_api_key(key_id, user_id)
        """
        try:
            async with self._get_session() as session:
                tenant_key = await self._revoke_api_key_impl(session, key_id, user_id)

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to revoke API key")
            raise BaseGiljoError(
                message=f"Failed to revoke API key: {e!s}", context={"key_id": key_id, "user_id": user_id}
            ) from e

        if notification_service is not None:
            await notification_service.resolve_by_dedupe_key(tenant_key, f"api_key.expiring_soon:{key_id}")

    async def _revoke_api_key_impl(self, session: AsyncSession, key_id: str, user_id: str) -> str:
        """Implementation that uses provided session. Returns the tenant_key."""
        tenant_key = await self._tenant_key_for_user(session, user_id)
        session.info["tenant_key"] = tenant_key
        api_key = await self._repo.get_api_key_by_id_and_user(session, key_id, user_id, tenant_key)

        if not api_key:
            raise ResourceNotFoundError(
                message="API key not found or access denied", context={"key_id": key_id, "user_id": user_id}
            )

        # Revoke key
        await self._repo.revoke_api_key(session, api_key, datetime.now(UTC))

        # BE-6060a: bust the MCP transport verdict cache so the revoked key stops
        # authenticating immediately rather than at the end of the TTL window.
        bust_api_key_cache(key_id)

        self._logger.info(
            f"API key revoked: {api_key.name} (user: {user_id})",
            extra={"user_id": sanitize(user_id), "key_id": sanitize(key_id), "key_name": sanitize(api_key.name)},
        )

        return tenant_key

    async def _tenant_key_for_user(
        self, session: AsyncSession, user_id: str, *, allow_missing: bool = False
    ) -> str | None:
        user = await self._repo.get_user_by_id(session, user_id)
        if not user:
            if allow_missing:
                return None
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})
        return user.tenant_key

    async def scan_expiring_api_keys(
        self,
        tenant_key: str,
        days_ahead: int = 7,
        notification_service: "NotificationService | None" = None,
    ) -> list[tuple[str, str, datetime, str]]:
        """Find API keys expiring within ``days_ahead`` days and notify owners.

        Tenant-scoped. Excludes revoked/inactive and already-expired keys, and
        keys with no expiry. For each expiring key, when ``notification_service``
        is provided, emits a de-duplicated ``api_key.expiring_soon`` notification
        (natural key ``api_key.expiring_soon:{api_key_id}`` — re-running the scan
        does not duplicate).

        Returns:
            ``[(user_id, api_key_id, expires_at, name)]`` for each expiring key.
        """
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days_ahead)

        async with self._get_session(tenant_key) as session:
            session.info["tenant_key"] = tenant_key
            keys = await self._repo.list_expiring_api_keys(session, tenant_key, now, cutoff)

        expiring: list[tuple[str, str, datetime, str]] = []
        for key in keys:
            expiring.append((key.user_id, str(key.id), key.expires_at, key.name))
            if notification_service is not None:
                await notification_service.create(
                    tenant_key=tenant_key,
                    user_id=key.user_id,
                    notification_type="api_key.expiring_soon",
                    severity="warning",
                    title=f"API key '{key.name}' expires soon",
                    body=f"Your API key '{key.name}' expires on {key.expires_at.isoformat()}.",
                    dedupe_key=f"api_key.expiring_soon:{key.id}",
                    payload={
                        "api_key_id": str(key.id),
                        "name": key.name,
                        "expires_at": key.expires_at.isoformat(),
                    },
                    expires_at=key.expires_at,
                )

        return expiring

    # ============================================================================
    # User Registration Methods
    # ============================================================================

    async def register_user(
        self,
        username: str,
        email: str | None,
        password: str,
        role: str,
        requesting_admin_id: str,
        registration_ip: str | None = None,
    ) -> UserInfo:
        """
        Register new user (admin-only operation).

        Args:
            username: Username for new user
            email: Email address (optional)
            password: Plaintext password (will be hashed)
            role: User role (admin, developer, viewer)
            requesting_admin_id: Admin user ID creating this user
            registration_ip: Client IP captured at registration (BE-6109),
                persisted for audit / abuse signal. Optional (nullable column).

        Returns:
            UserInfo with id, username, email, role, and tenant_key

        Raises:
            ValidationError: If username/email already exists
            BaseGiljoError: For other errors

        Example:
            >>> user = await service.register_user(
            ...     "newuser", "new@example.com", "Password123!", "developer", admin_id
            ... )
            >>> print(user.tenant_key)
        """
        try:
            async with self._get_session() as session:
                return await self._register_user_impl(
                    session, username, email, password, role, requesting_admin_id, registration_ip=registration_ip
                )

        except ValidationError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to register user")
            raise BaseGiljoError(message=f"Failed to register user: {e!s}", context={"username": username}) from e

    async def _register_user_impl(
        self,
        session: AsyncSession,
        username: str,
        email: str | None,
        password: str,
        role: str,
        requesting_admin_id: str,
        org_id: str | None = None,
        org_role: str = "member",
        registration_ip: str | None = None,
    ) -> UserInfo:
        """Implementation that uses provided session."""
        # Check for duplicate username
        if await self._repo.check_username_exists(session, username):
            raise ValidationError(
                message=f"Username '{username}' already exists", context={"username": username, "field": "username"}
            )

        # Check for duplicate email if provided
        if email and await self._repo.check_email_exists(session, email):
            raise ValidationError(message=f"Email '{email}' already exists", context={"email": email, "field": "email"})

        # Hash off the event loop via the shared helper
        password_hash = await async_hash_password(password)

        # Generate per-user tenant key
        tenant_key = TenantManager.generate_tenant_key(username)

        # Create user with optional org_id (Handover 0424g)
        new_user = User(
            id=str(uuid4()),
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            tenant_key=tenant_key,
            org_id=org_id,  # Set org_id if provided (Handover 0424g)
            is_active=True,
            created_at=datetime.now(UTC),
            registration_ip=registration_ip,  # BE-6109: audit / abuse signal
        )

        await self._repo.create_user(session, new_user)

        # Create organization membership if org_id provided (Handover 0424g)
        if org_id:
            from giljo_mcp.models.organizations import OrgMembership

            membership = OrgMembership(
                org_id=org_id, user_id=str(new_user.id), tenant_key=tenant_key, role=org_role, is_active=True
            )
            await self._repo.create_org_membership(session, membership)
        else:
            # Create default organization for user without org_id (backward compatibility)
            created_org_id = await self._create_default_organization(
                session=session, tenant_key=tenant_key, org_name=f"{username}'s Workspace"
            )
            new_user.org_id = created_org_id
            # Create owner membership for their own org
            from giljo_mcp.models.organizations import OrgMembership

            membership = OrgMembership(
                org_id=created_org_id, user_id=str(new_user.id), tenant_key=tenant_key, role="owner", is_active=True
            )
            await self._repo.create_org_membership(session, membership)

        await session.commit()
        await session.refresh(new_user)

        self._logger.info(
            f"User registered: {sanitize(username)} (role: {sanitize(role)}, org_role: {sanitize(org_role)}, "
            f"by admin: {sanitize(requesting_admin_id)})",
            extra={
                "username": sanitize(username),
                "role": sanitize(role),
                "org_role": sanitize(org_role),
                "admin_id": sanitize(requesting_admin_id),
            },
        )

        return UserInfo(
            id=str(new_user.id),
            username=new_user.username,
            email=new_user.email,
            role=new_user.role,
            tenant_key=new_user.tenant_key,
        )

    async def create_user_in_org(
        self, session: AsyncSession, admin_user_id: str, username: str, email: str, role: str, initial_password: str
    ) -> UserInfo:
        """
        Create user within admin's organization (Handover 0424g).

        Admin/owner creates new user in their organization. New user inherits
        admin's org_id and receives specified membership role.

        Args:
            session: Database session
            admin_user_id: Admin user ID (must have owner/admin role in org)
            username: Username for new user
            email: Email address
            role: Organization membership role (owner/admin/member/viewer)
            initial_password: Initial password for new user

        Returns:
            UserInfo with the new user's id, username, email, role, and tenant_key

        Raises:
            AuthorizationError: If admin doesn't have owner/admin role
            ValidationError: If username/email already exists

        Example:
            >>> user = await service.create_user_in_org(
            ...     session, admin_id, "newuser", "new@example.com", "member", "TempPass123!"
            ... )
        """

        # Verify admin has owner/admin role in their organization
        admin = await self._repo.get_user_with_org(session, admin_user_id)

        if not admin or not admin.org_id:
            raise AuthorizationError(
                message="Admin user not found or not member of any organization",
                context={"admin_user_id": admin_user_id},
            )

        # Check admin's membership role (must be owner or admin)
        membership = await self._repo.get_org_membership(session, admin.org_id, admin_user_id)

        if not membership or membership.role not in ("owner", "admin"):
            raise AuthorizationError(
                message="Only organization owners and admins can create users",
                context={
                    "admin_user_id": admin_user_id,
                    "org_id": admin.org_id,
                    "current_role": membership.role if membership else None,
                },
            )

        # Create user in admin's organization
        return await self._register_user_impl(
            session=session,
            username=username,
            email=email,
            password=initial_password,
            role="developer",  # User.role (system role, not org role)
            requesting_admin_id=admin_user_id,
            org_id=admin.org_id,  # Inherit admin's org_id
            org_role=role,  # OrgMembership.role (owner/admin/member/viewer)
        )

    async def create_first_admin(
        self,
        username: str,
        email: str | None,
        password: str,
        full_name: str | None,
        org_name: str | None = "My Organization",
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> AuthResult:
        """
        Create first administrator account (fresh install only).

        Args:
            username: Admin username
            email: Admin email (optional)
            password: Admin password (must meet complexity requirements)
            full_name: Legacy combined name (deprecated -- prefer first_name/
                last_name). Used as a fallback when first_name/last_name are
                both omitted.
            org_name: Organization name (default: "My Organization") - Handover 0424h
            first_name: Given name (preferred). Defaults to "Administrator"
                when both first_name and last_name are blank and no legacy
                full_name was supplied.
            last_name: Family name (optional)

        Returns:
            AuthResult with user_id, username, token, tenant_key, role,
            and profile fields for the newly created admin

        Raises:
            ValidationError: If admin already exists or password too weak
            BaseGiljoError: For other errors

        Example:
            >>> admin = await service.create_first_admin(
            ...     "admin", "admin@example.com", "SecureAdmin123!@#", "Administrator",
            ...     org_name="Acme Corporation"
            ... )
            >>> token = admin.token
        """
        try:
            async with self._get_session() as session:
                return await self._create_first_admin_impl(
                    session, username, email, password, full_name, org_name, first_name, last_name
                )

        except ValidationError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to create first admin")
            raise BaseGiljoError(message=f"Failed to create first admin: {e!s}", context={"username": username}) from e

    async def _create_first_admin_impl(
        self,
        session: AsyncSession,
        username: str,
        email: str | None,
        password: str,
        full_name: str | None,
        org_name: str | None = "My Organization",
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> AuthResult:
        """Implementation that uses provided session (Handover 0424h: accepts org_name)."""
        # Check if users already exist (must be fresh install)
        total_users = await self._repo.get_total_user_count(session)

        if total_users > 0:
            raise ValidationError(
                message="Administrator account already exists", context={"reason": "users_exist", "count": total_users}
            )

        # Validate password strength (8+ chars, complexity)
        if len(password) < 8:
            raise ValidationError(
                message="Password must be at least 8 characters",
                context={"password_length": len(password), "required": 8},
            )

        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)

        if not (has_upper and has_lower and has_digit and has_special):
            raise ValidationError(
                message="Password must contain uppercase, lowercase, digit, and special character",
                context={
                    "has_uppercase": has_upper,
                    "has_lowercase": has_lower,
                    "has_digit": has_digit,
                    "has_special": has_special,
                },
            )

        # Hash off the event loop via the shared helper
        password_hash = await async_hash_password(password)

        tenant_key = TenantManager.generate_tenant_key(username)

        # INF-6174d: mint the JWT BEFORE any DB write — a post-commit mint failure
        # stranded this one-shot endpoint; fail-first = clean abort + retry.
        admin_user_id = str(uuid4())
        token = JWTManager.create_access_token(
            user_id=admin_user_id,
            username=username,
            role="admin",
            tenant_key=tenant_key,
            revocation_epoch=0,
        )

        # Org FIRST (HO 0424g org-first pattern; 0424h: caller-provided org_name)
        org_id = await self._create_default_organization(
            session=session, tenant_key=tenant_key, org_name=org_name or "My Organization"
        )

        # Resolve name fields. Prefer first/last; fall back to legacy
        # full_name; default first_name to "Administrator" when nothing
        # else was supplied. Dual-write full_name as a transition shim.
        resolved_first = first_name
        resolved_last = last_name
        if not resolved_first and not resolved_last:
            if full_name and full_name.strip():
                resolved_first = full_name.strip()
            else:
                resolved_first = "Administrator"

        resolved_full_name = " ".join(p for p in (resolved_first, resolved_last) if p).strip() or None

        admin_user = User(
            id=admin_user_id,
            username=username,
            email=email,
            first_name=resolved_first,
            last_name=resolved_last,
            full_name=resolved_full_name,
            password_hash=password_hash,
            role="admin",  # Force admin role
            tenant_key=tenant_key,
            org_id=org_id,  # Direct FK to organization (Handover 0424g)
            is_active=True,
            created_at=datetime.now(UTC),
        )

        await self._repo.create_user(session, admin_user)

        # Create owner membership (Handover 0424g)
        from giljo_mcp.models.organizations import OrgMembership

        owner_membership = OrgMembership(
            org_id=org_id, user_id=str(admin_user.id), tenant_key=tenant_key, role="owner", is_active=True
        )
        await self._repo.create_org_membership(session, owner_membership)
        await session.commit()
        await session.refresh(admin_user)

        # Mark first admin created in SetupState
        setup_state = await self._repo.get_setup_state(session, tenant_key)

        if setup_state:
            setup_state.first_admin_created = True
            setup_state.first_admin_created_at = datetime.now(UTC)
        else:
            setup_state = SetupState(
                id=str(uuid4()),
                tenant_key=tenant_key,
                database_initialized=True,
                database_initialized_at=datetime.now(UTC),
                first_admin_created=True,
                first_admin_created_at=datetime.now(UTC),
            )
            await self._repo.create_setup_state(session, setup_state)

        await session.commit()

        self._logger.info(
            f"First administrator account created: {sanitize(username)}",
            extra={"username": sanitize(username), "tenant_key": sanitize(tenant_key)},
        )

        return AuthResult(
            user_id=str(admin_user.id),
            username=admin_user.username,
            token=token,
            tenant_key=admin_user.tenant_key,
            role=admin_user.role,
            email=admin_user.email,
            first_name=admin_user.first_name,
            last_name=admin_user.last_name,
            full_name=admin_user.full_name,
            is_active=admin_user.is_active,
            created_at=admin_user.created_at.isoformat() if admin_user.created_at else None,
        )

    # ============================================================================
    # Organization Helper Methods (Handover 0424b)
    # ============================================================================

    async def _create_default_organization(
        self, session: AsyncSession, tenant_key: str, org_name: str = "My Workspace"
    ) -> str:
        """
        Create default organization (Handover 0424g: org-first pattern).

        This method creates an organization WITHOUT creating membership.
        Caller is responsible for creating user and membership.

        Args:
            session: Database session
            tenant_key: Tenant isolation key
            org_name: Custom organization name (default: "My Workspace")

        Returns:
            org.id as UUID string

        Note: This method adds org to session without committing.
        Parent methods (_register_user_impl, _create_first_admin_impl) handle commit.
        """
        import re
        from uuid import uuid4

        from giljo_mcp.models.organizations import Organization

        # Generate slug from org_name (sanitize and make URL-friendly)
        slug_base = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-")
        slug = f"{slug_base}-{str(uuid4())[:8]}"  # Add UUID suffix for uniqueness

        # Create organization
        org = Organization(name=org_name, tenant_key=tenant_key, slug=slug, settings={})
        org = await self._repo.create_organization(session, org)

        # No commit here - parent method handles it
        self._logger.info(
            f"Organization created: {sanitize(org_name)}",
            extra={"tenant_key": sanitize(tenant_key), "org_id": sanitize(org.id), "slug": sanitize(slug)},
        )

        return str(org.id)
