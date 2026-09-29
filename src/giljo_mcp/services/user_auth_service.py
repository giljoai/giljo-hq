# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.auth import User
from giljo_mcp.repositories.user_repository import UserRepository
from giljo_mcp.services._session_helpers import tenant_context_session
from giljo_mcp.services.login_lockout_service import LoginLockoutService
from giljo_mcp.services.oauth_refresh_service import (
    revoke_all_for_user as revoke_all_refresh_tokens_for_user,
)
from giljo_mcp.services.session_eviction import evict_user_tokens
from giljo_mcp.utils.password_helper import async_hash_password, async_verify_password


logger = logging.getLogger(__name__)


class UserAuthService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        websocket_manager=None,
        session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._websocket_manager = websocket_manager
        self._session = session
        self._repo = UserRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        return tenant_context_session(self.db_manager, self.tenant_key, self._session)

    async def change_password(
        self, user_id: str, old_password: str | None, new_password: str, is_admin: bool = False
    ) -> None:
        try:
            async with self._get_session() as session:
                return await self._change_password_impl(session, user_id, old_password, new_password, is_admin)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to change password")
            raise BaseGiljoError(message=str(e), context={"operation": "change_password", "user_id": user_id}) from e

    async def _change_password_impl(
        self, session: AsyncSession, user_id: str, old_password: str | None, new_password: str, is_admin: bool
    ) -> None:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        if not is_admin:
            if not old_password:
                raise ValidationError(message="Current password is required", context={"user_id": user_id})

            if not await async_verify_password(old_password, user.password_hash):
                raise AuthenticationError(message="Current password is incorrect", context={"user_id": user_id})

        user.password_hash = await async_hash_password(new_password)
        user.must_change_password = False

        await session.execute(
            select(User.id).where(User.id == str(user.id), User.tenant_key == self.tenant_key).with_for_update()
        )

        user.token_revocation_epoch = (user.token_revocation_epoch or 0) + 1
        revoked_count = await revoke_all_refresh_tokens_for_user(
            session, user_id=str(user.id), tenant_key=self.tenant_key
        )

        await session.commit()

        self._logger.info(
            f"Password changed for user: {user.username} "
            f"(revocation epoch bumped to {user.token_revocation_epoch}, "
            f"{revoked_count} refresh token(s) revoked)"
        )

    async def set_initial_password(self, user_id: str, new_password: str) -> None:
        try:
            async with self._get_session() as session:
                return await self._set_initial_password_impl(session, user_id, new_password)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to set initial password")
            raise BaseGiljoError(
                message=str(e), context={"operation": "set_initial_password", "user_id": user_id}
            ) from e

    async def _set_initial_password_impl(self, session: AsyncSession, user_id: str, new_password: str) -> None:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        if user.password_hash is not None:
            raise AuthorizationError(
                message="A password is already set for this account. Use change password instead.",
                context={"user_id": user_id},
            )

        user.password_hash = await async_hash_password(new_password)
        user.must_change_password = False
        user.password_nudge_dismissed_at = datetime.now(UTC)

        await session.commit()

        self._logger.info(f"Initial password set for user: {user.username}")

    async def verify_password(self, user_id: str, password: str) -> bool:
        try:
            async with self._get_session() as session:
                return await self._verify_password_impl(session, user_id, password)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to verify password")
            raise BaseGiljoError(message=str(e), context={"operation": "verify_password", "user_id": user_id}) from e

    async def _verify_password_impl(self, session: AsyncSession, user_id: str, password: str) -> bool:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        return await async_verify_password(password, user.password_hash)


    async def check_username_exists(self, username: str) -> bool:
        try:
            async with self._get_session() as session:
                return await self._repo.check_username_exists(session, username)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to check username")
            raise BaseGiljoError(
                message=str(e), context={"operation": "check_username_exists", "username": username}
            ) from e

    async def check_email_exists(self, email: str) -> bool:
        try:
            async with self._get_session() as session:
                return await self._repo.check_email_exists(session, email)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to check email")
            raise BaseGiljoError(message=str(e), context={"operation": "check_email_exists", "email": email}) from e


    async def change_role(self, user_id: str, new_role: str) -> User:
        try:
            async with self._get_session() as session:
                return await self._change_role_impl(session, user_id, new_role)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to change role")
            raise BaseGiljoError(
                message=str(e), context={"operation": "change_role", "user_id": user_id, "new_role": new_role}
            ) from e

    async def _change_role_impl(self, session: AsyncSession, user_id: str, new_role: str) -> User:
        valid_roles = ["admin", "developer", "viewer"]
        if new_role not in valid_roles:
            raise ValidationError(
                message=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
                context={"new_role": new_role, "valid_roles": valid_roles},
            )

        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        if user.role == "admin" and new_role != "admin":
            admin_count = await self._repo.count_admins_excluding(session, self.tenant_key, user_id)

            if admin_count == 0:
                raise AuthorizationError(
                    message="Cannot demote the last admin. At least one admin must remain.",
                    context={"user_id": user_id, "current_role": "admin", "new_role": new_role},
                )

        old_role = user.role
        user.role = new_role
        await session.commit()
        await session.refresh(user)

        self._logger.info(f"Changed role for user {user.username}: {old_role} -> {new_role}")

        return user

    async def force_logout(self, user_id: str) -> User:
        try:
            async with self._get_session() as session:
                return await self._force_logout_impl(session, user_id)
        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to force logout")
            raise BaseGiljoError(message=str(e), context={"operation": "force_logout", "user_id": user_id}) from e

    async def _force_logout_impl(self, session: AsyncSession, user_id: str) -> User:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        await session.execute(
            select(User.id).where(User.id == str(user.id), User.tenant_key == self.tenant_key).with_for_update()
        )

        user.token_revocation_epoch = (user.token_revocation_epoch or 0) + 1
        revoked_count = await revoke_all_refresh_tokens_for_user(
            session, user_id=str(user.id), tenant_key=self.tenant_key
        )
        await session.commit()
        await session.refresh(user)

        self._logger.info(
            f"Force-logout: bumped revocation epoch for user {user.username} to "
            f"{user.token_revocation_epoch} ({revoked_count} refresh token(s) revoked)"
        )
        return user




async def record_failed_pin_attempt(session: AsyncSession, user: User) -> None:
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    await session.refresh(user, attribute_names=["failed_pin_attempts", "pin_lockout_until"])
    user.failed_pin_attempts += 1
    if user.failed_pin_attempts >= 5:
        user.pin_lockout_until = datetime.now(UTC) + timedelta(minutes=15)
    await session.commit()


async def reset_password_via_pin(session: AsyncSession, user: User, new_password: str) -> int:
    user.password_hash = await async_hash_password(new_password)
    user.failed_pin_attempts = 0
    user.pin_lockout_until = None

    with tenant_session_context(session, user.tenant_key):
        revoked_count = await evict_user_tokens(session, user)

    try:
        await LoginLockoutService().clear_for_identifiers(session, [user.username, user.email])
    except Exception:  # noqa: BLE001 - never block a password reset on lockout cleanup
        logger.warning("login lockout clear on PIN reset failed", exc_info=True)

    await session.commit()
    return revoked_count
