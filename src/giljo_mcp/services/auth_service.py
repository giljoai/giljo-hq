# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    def __init__(self, db_manager: DatabaseManager, websocket_manager=None, session: AsyncSession | None = None):
        self.db_manager = db_manager
        self._websocket_manager = websocket_manager
        self._session = session
        self._repo = AuthRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self, tenant_key: str | None = None):
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


    async def authenticate_user(self, username: str, password: str) -> AuthResult:
        try:
            async with self._get_session() as session:
                user = await self._repo.get_user_by_username(session, username)
                if user is None:
                    user = await self._repo.get_user_by_email(session, username)

            return await self._authenticate_user_impl(user, username, password)

        except (AuthenticationError, AuthorizationError):
            raise
        except Exception as e:
            self._logger.exception("Failed to authenticate user")
            raise BaseGiljoError(message=f"Authentication failed: {e!s}", context={"identifier": username}) from e

    async def _authenticate_user_impl(self, user: User | None, username: str, password: str) -> AuthResult:
        stored = user.password_hash if user is not None else None
        password_ok = await async_verify_password(password, stored or DUMMY_BCRYPT_HASH) and stored is not None

        if not password_ok:
            self._logger.warning(
                f"Authentication failed for identifier: {sanitize(username)}",
                extra={"identifier": sanitize(username), "reason": "invalid_credentials"},
            )
            raise AuthenticationError(message="Invalid credentials", context={"identifier": username})

        if not user.is_active:
            self._logger.warning(
                f"Authentication failed for identifier: {sanitize(username)} (inactive account)",
                extra={"identifier": sanitize(username), "user_id": sanitize(user.id), "reason": "inactive_account"},
            )
            raise AuthorizationError(
                message="User account is inactive", context={"identifier": username, "user_id": user.id}
            )

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
        try:
            async with self._get_session() as session:
                await self._update_last_login_impl(session, user_id, timestamp)

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to update last login")
            raise BaseGiljoError(message=f"Failed to update last login: {e!s}", context={"user_id": user_id}) from e

    async def _update_last_login_impl(self, session: AsyncSession, user_id: str, timestamp: datetime) -> None:
        user = await self._repo.get_user_by_id(session, user_id)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        await self._repo.update_last_login(session, user, timestamp)

        self._logger.debug(
            f"Updated last login for user {user_id}", extra={"user_id": user_id, "timestamp": timestamp.isoformat()}
        )


    async def check_setup_state(self, tenant_key: str) -> SetupStateInfo | None:
        try:
            async with self._get_session(tenant_key) as session:
                return await self._check_setup_state_impl(session, tenant_key)

        except Exception as e:
            self._logger.exception("Failed to check setup state")
            raise BaseGiljoError(
                message=f"Failed to check setup state: {e!s}", context={"tenant_key": tenant_key}
            ) from e

    async def _check_setup_state_impl(self, session: AsyncSession, tenant_key: str) -> SetupStateInfo | None:
        setup_state = await self._repo.get_setup_state(session, tenant_key)

        if not setup_state:
            return None

        return SetupStateInfo(
            first_admin_created=setup_state.first_admin_created,
            database_initialized=setup_state.database_initialized,
            tenant_key=setup_state.tenant_key,
        )


    async def list_api_keys(self, user_id: str, include_revoked: bool = False) -> list[ApiKeyInfo]:
        try:
            async with self._get_session() as session:
                return await self._list_api_keys_impl(session, user_id, include_revoked)

        except Exception as e:
            self._logger.exception("Failed to list API keys")
            raise BaseGiljoError(message=f"Failed to list API keys: {e!s}", context={"user_id": user_id}) from e

    async def _list_api_keys_impl(self, session: AsyncSession, user_id: str, include_revoked: bool) -> list[ApiKeyInfo]:
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
        try:
            async with self._get_session(tenant_key) as session:
                result = await self._create_api_key_impl(session, user_id, tenant_key, name, permissions)

        except BaseGiljoError:
            raise
        except Exception as e:
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

        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        key_prefix = get_key_prefix(api_key, length=12)

        from giljo_mcp.schemas.jsonb_validators import validate_api_key_permissions

        validated_permissions = validate_api_key_permissions(permissions) or []

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
            api_key=api_key,
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
        try:
            async with self._get_session() as session:
                tenant_key = await self._revoke_api_key_impl(session, key_id, user_id)

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to revoke API key")
            raise BaseGiljoError(
                message=f"Failed to revoke API key: {e!s}", context={"key_id": key_id, "user_id": user_id}
            ) from e

        if notification_service is not None:
            await notification_service.resolve_by_dedupe_key(tenant_key, f"api_key.expiring_soon:{key_id}")

    async def _revoke_api_key_impl(self, session: AsyncSession, key_id: str, user_id: str) -> str:
        tenant_key = await self._tenant_key_for_user(session, user_id)
        session.info["tenant_key"] = tenant_key
        api_key = await self._repo.get_api_key_by_id_and_user(session, key_id, user_id, tenant_key)

        if not api_key:
            raise ResourceNotFoundError(
                message="API key not found or access denied", context={"key_id": key_id, "user_id": user_id}
            )

        await self._repo.revoke_api_key(session, api_key, datetime.now(UTC))

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


    async def register_user(
        self,
        username: str,
        email: str | None,
        password: str,
        role: str,
        requesting_admin_id: str,
        registration_ip: str | None = None,
    ) -> UserInfo:
        try:
            async with self._get_session() as session:
                return await self._register_user_impl(
                    session, username, email, password, role, requesting_admin_id, registration_ip=registration_ip
                )

        except ValidationError:
            raise
        except Exception as e:
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
        if await self._repo.check_username_exists(session, username):
            raise ValidationError(
                message=f"Username '{username}' already exists", context={"username": username, "field": "username"}
            )

        if email and await self._repo.check_email_exists(session, email):
            raise ValidationError(message=f"Email '{email}' already exists", context={"email": email, "field": "email"})

        password_hash = await async_hash_password(password)

        tenant_key = TenantManager.generate_tenant_key(username)

        new_user = User(
            id=str(uuid4()),
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            tenant_key=tenant_key,
            org_id=org_id,
            is_active=True,
            created_at=datetime.now(UTC),
            registration_ip=registration_ip,
        )

        await self._repo.create_user(session, new_user)

        if org_id:
            from giljo_mcp.models.organizations import OrgMembership

            membership = OrgMembership(
                org_id=org_id, user_id=str(new_user.id), tenant_key=tenant_key, role=org_role, is_active=True
            )
            await self._repo.create_org_membership(session, membership)
        else:
            created_org_id = await self._create_default_organization(
                session=session, tenant_key=tenant_key, org_name=f"{username}'s Workspace"
            )
            new_user.org_id = created_org_id
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

        admin = await self._repo.get_user_with_org(session, admin_user_id)

        if not admin or not admin.org_id:
            raise AuthorizationError(
                message="Admin user not found or not member of any organization",
                context={"admin_user_id": admin_user_id},
            )

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

        return await self._register_user_impl(
            session=session,
            username=username,
            email=email,
            password=initial_password,
            role="developer",
            requesting_admin_id=admin_user_id,
            org_id=admin.org_id,
            org_role=role,
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
        try:
            async with self._get_session() as session:
                return await self._create_first_admin_impl(
                    session, username, email, password, full_name, org_name, first_name, last_name
                )

        except ValidationError:
            raise
        except Exception as e:
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
        total_users = await self._repo.get_total_user_count(session)

        if total_users > 0:
            raise ValidationError(
                message="Administrator account already exists", context={"reason": "users_exist", "count": total_users}
            )

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

        password_hash = await async_hash_password(password)

        tenant_key = TenantManager.generate_tenant_key(username)

        admin_user_id = str(uuid4())
        token = JWTManager.create_access_token(
            user_id=admin_user_id,
            username=username,
            role="admin",
            tenant_key=tenant_key,
            revocation_epoch=0,
        )

        org_id = await self._create_default_organization(
            session=session, tenant_key=tenant_key, org_name=org_name or "My Organization"
        )

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
            role="admin",
            tenant_key=tenant_key,
            org_id=org_id,
            is_active=True,
            created_at=datetime.now(UTC),
        )

        await self._repo.create_user(session, admin_user)

        from giljo_mcp.models.organizations import OrgMembership

        owner_membership = OrgMembership(
            org_id=org_id, user_id=str(admin_user.id), tenant_key=tenant_key, role="owner", is_active=True
        )
        await self._repo.create_org_membership(session, owner_membership)
        await session.commit()
        await session.refresh(admin_user)

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


    async def _create_default_organization(
        self, session: AsyncSession, tenant_key: str, org_name: str = "My Workspace"
    ) -> str:
        import re
        from uuid import uuid4

        from giljo_mcp.models.organizations import Organization

        slug_base = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-")
        slug = f"{slug_base}-{str(uuid4())[:8]}"

        org = Organization(name=org_name, tenant_key=tenant_key, slug=slug, settings={})
        org = await self._repo.create_organization(session, org)

        self._logger.info(
            f"Organization created: {sanitize(org_name)}",
            extra={"tenant_key": sanitize(tenant_key), "org_id": sanitize(org.id), "slug": sanitize(slug)},
        )

        return str(org.id)
