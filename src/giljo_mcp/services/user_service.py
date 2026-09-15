# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.auth import TOGGLEABLE_CATEGORIES, User, UserFieldPriority
from giljo_mcp.repositories.user_repository import UserRepository
from giljo_mcp.services._session_helpers import tenant_context_session
from giljo_mcp.services.session_eviction import close_live_user_sockets, evict_user_tokens
from giljo_mcp.services.user_auth_service import UserAuthService
from giljo_mcp.utils.log_sanitizer import sanitize
from giljo_mcp.utils.password_helper import async_hash_password


logger = logging.getLogger(__name__)


class UserService:

    def __init__(
        self, db_manager: DatabaseManager, tenant_key: str, websocket_manager=None, session: AsyncSession | None = None
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._websocket_manager = websocket_manager
        self._session = session
        self._repo = UserRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.auth = UserAuthService(db_manager, tenant_key, websocket_manager, session)

    def _get_session(self, tenant_key: str | None = None):
        return tenant_context_session(self.db_manager, tenant_key or self.tenant_key, self._session)

    async def list_users(self, include_all_tenants: bool = False, tenant_key: str | None = None) -> list[User]:
        try:
            effective_tenant_key = tenant_key if tenant_key is not None else self.tenant_key
            async with self._get_session(effective_tenant_key) as session:
                return await self._list_users_impl(session, include_all_tenants, tenant_key)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to list users")
            raise BaseGiljoError(
                message=str(e), context={"operation": "list_users", "tenant_key": self.tenant_key}
            ) from e

    async def _list_users_impl(
        self,
        session: AsyncSession,
        include_all_tenants: bool = False,
        tenant_key: str | None = None,
    ) -> list[User]:
        effective_tenant_key = tenant_key if tenant_key is not None else self.tenant_key
        users = await self._repo.list_users(session, effective_tenant_key, include_all_tenants)

        log_msg = f"Found {len(users)} users" + (
            " (all tenants)" if include_all_tenants else f" for tenant {effective_tenant_key}"
        )
        self._logger.debug(log_msg)

        return users

    async def get_user(self, user_id: str, include_all_tenants: bool = False) -> User:
        try:
            async with self._get_session() as session:
                return await self._get_user_impl(session, user_id, include_all_tenants)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to get user")
            raise BaseGiljoError(message=str(e), context={"operation": "get_user", "user_id": user_id}) from e

    async def _get_user_impl(self, session: AsyncSession, user_id: str, include_all_tenants: bool = False) -> User:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key, include_all_tenants)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        self._logger.info("Fetched user", extra={"user_id": sanitize(user_id)})

        return user

    async def create_user(
        self,
        username: str,
        email: str | None = None,
        full_name: str | None = None,
        password: str | None = None,
        role: str = "developer",
        is_active: bool = True,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        if not password:
            raise ValidationError(
                message="password is required to create a user",
                context={"operation": "create_user", "username": username},
            )

        try:
            async with self._get_session() as session:
                return await self._create_user_impl(
                    session, username, email, full_name, password, role, is_active, first_name, last_name
                )

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to create user")
            raise BaseGiljoError(message=str(e), context={"operation": "create_user", "username": username}) from e

    async def _create_user_impl(
        self,
        session: AsyncSession,
        username: str,
        email: str | None,
        full_name: str | None,
        password: str | None,
        role: str,
        is_active: bool,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        if await self._repo.check_username_exists(session, username):
            raise ValidationError(message=f"Username '{username}' already exists", context={"username": username})

        if email and await self._repo.check_email_exists(session, email):
            raise ValidationError(message=f"Email '{email}' already exists", context={"email": email})

        if not password:
            raise ValidationError(
                message="password is required to create a user",
                context={"operation": "create_user", "username": username},
            )
        password_hash = await async_hash_password(password)

        if first_name or last_name:
            derived_full_name = " ".join(p for p in (first_name, last_name) if p).strip() or None
        else:
            derived_full_name = full_name

        user = User(
            id=str(uuid4()),
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            full_name=derived_full_name,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            tenant_key=self.tenant_key,
            must_change_password=False,
            must_set_pin=True,
            recovery_pin_hash=None,
            created_at=datetime.now(UTC),
        )

        user = await self._repo.add_user(session, user)

        self._logger.info(f"Created user {user.id} for tenant {self.tenant_key}")

        return user

    async def update_user(self, user_id: str, include_all_tenants: bool = False, **updates) -> User:
        try:
            async with self._get_session() as session:
                return await self._update_user_impl(session, user_id, updates, include_all_tenants)

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to update user")
            raise BaseGiljoError(message=str(e), context={"operation": "update_user", "user_id": user_id}) from e

    async def _update_user_impl(
        self, session: AsyncSession, user_id: str, updates: dict, include_all_tenants: bool = False
    ) -> User:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key, include_all_tenants)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        if (
            "username" in updates
            and updates["username"]
            and updates["username"] != user.username
            and await self._repo.check_username_exists(session, updates["username"])
        ):
            raise ValidationError(
                message=f"Username '{updates['username']}' already taken",
                context={"username": updates["username"], "user_id": user_id},
            )

        if (
            "email" in updates
            and updates["email"]
            and updates["email"] != user.email
            and await self._repo.check_email_exists(session, updates["email"])
        ):
            raise ValidationError(
                message=f"Email '{updates['email']}' already exists",
                context={"email": updates["email"], "user_id": user_id},
            )

        old_email = user.email

        allowed_fields = {"username", "email", "full_name", "is_active", "first_name", "last_name"}
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(user, field, value)

        if "first_name" in updates or "last_name" in updates:
            parts = [p for p in (user.first_name, user.last_name) if p]
            user.full_name = " ".join(parts).strip() or None

        if updates.get("password"):
            user.password_hash = await async_hash_password(updates["password"])

        deactivating = updates.get("is_active") is False
        if updates.get("password") or deactivating:
            revoked = await evict_user_tokens(session, user)
            self._logger.info(
                f"Sessions evicted for user {sanitize(user_id)} "
                f"(epoch->{user.token_revocation_epoch}, {revoked} revoked)"
            )

        await session.commit()
        await session.refresh(user)

        self._logger.info(f"Updated user {sanitize(user_id)}")

        if deactivating:
            await close_live_user_sockets(user.tenant_key, self._logger)

        if "email" in updates and updates["email"] and updates["email"] != old_email:
            await self._emit_email_changed(user, old_email)

        return user

    async def _emit_email_changed(self, user: User, old_email: str | None) -> None:
        try:
            from api.app_state import state

            if getattr(state, "event_bus", None):
                await state.event_bus.publish(
                    "user:email:changed",
                    {
                        "tenant_key": self.tenant_key,
                        "user_id": str(user.id),
                        "org_id": str(user.org_id) if user.org_id else None,
                        "old_email": old_email,
                        "new_email": user.email,
                    },
                )
        except Exception:  # noqa: BLE001 - fire-and-forget signal, never fail the update
            self._logger.warning("Failed to publish user:email:changed signal", exc_info=True)

    async def delete_user(self, user_id: str) -> None:
        try:
            async with self._get_session() as session:
                await self._delete_user_impl(session, user_id)
            await close_live_user_sockets(self.tenant_key, self._logger)
            return

        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to delete user")
            raise BaseGiljoError(message=str(e), context={"operation": "delete_user", "user_id": user_id}) from e

    async def _delete_user_impl(self, session: AsyncSession, user_id: str) -> None:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)

        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        await self._repo.soft_delete_user(session, user)

        await evict_user_tokens(session, user)

        self._logger.info(f"Soft deleted user {sanitize(user_id)}")


    async def update_notification_preferences(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from giljo_mcp.config.defaults import DEFAULT_NOTIFICATION_PREFERENCES
        from giljo_mcp.schemas.jsonb_validators import validate_notification_preferences

        try:
            async with self._get_session() as session:
                user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
                if not user:
                    raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

                prefs = dict(user.notification_preferences or DEFAULT_NOTIFICATION_PREFERENCES)

                if "context_tuning_reminder" in payload:
                    prefs["context_tuning_reminder"] = bool(payload["context_tuning_reminder"])

                if "tuning_reminder_threshold" in payload:
                    threshold = int(payload["tuning_reminder_threshold"])
                    prefs["tuning_reminder_threshold"] = max(threshold, 3)

                if "banner_lifecycle_enabled" in payload:
                    prefs["banner_lifecycle_enabled"] = bool(payload["banner_lifecycle_enabled"])

                if "banner_advisories_in_fold" in payload:
                    prefs["banner_advisories_in_fold"] = bool(payload["banner_advisories_in_fold"])

                if "popout_scope" in payload:
                    prefs["popout_scope"] = payload["popout_scope"]

                prefs = validate_notification_preferences(prefs)

                user.notification_preferences = prefs
                await session.commit()

                self._logger.info("Updated notification preferences for user %s", user_id)
                return prefs

        except (ResourceNotFoundError, ValidationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to update notification preferences")
            raise BaseGiljoError(
                message=str(e),
                context={"operation": "update_notification_preferences", "user_id": user_id},
            ) from e

    async def set_recovery_pin(self, user_id: str, recovery_pin: str) -> None:
        if not (isinstance(recovery_pin, str) and len(recovery_pin) == 4 and recovery_pin.isdigit()):
            raise ValidationError(
                message="Recovery PIN must be exactly 4 digits",
                context={"user_id": user_id},
            )

        try:
            async with self._get_session() as session:
                user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
                if not user:
                    raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

                user.recovery_pin_hash = await async_hash_password(recovery_pin)
                await session.commit()

                self._logger.info("Recovery PIN updated for user %s", sanitize(user_id))

        except (ResourceNotFoundError, ValidationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to set recovery PIN")
            raise BaseGiljoError(
                message=str(e),
                context={"operation": "set_recovery_pin", "user_id": user_id},
            ) from e


    async def get_field_priority_config(self, user_id: str) -> dict[str, Any]:
        try:
            async with self._get_session() as session:
                return await self._get_field_priority_config_impl(session, user_id)
        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to get field priority config")
            raise BaseGiljoError(
                message=str(e), context={"operation": "get_field_priority_config", "user_id": user_id}
            ) from e

    async def _get_field_priority_config_impl(self, session: AsyncSession, user_id: str) -> dict[str, Any]:
        from giljo_mcp.config.defaults import DEFAULT_CATEGORY_TOGGLES, DEFAULT_FIELD_PRIORITY

        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        rows = await self._repo.get_field_priorities(session, user_id, self.tenant_key)

        if not rows:
            return DEFAULT_FIELD_PRIORITY

        toggles = dict(DEFAULT_CATEGORY_TOGGLES)
        for row in rows:
            toggles[row.category] = row.enabled

        priorities = {
            "product_core": {"toggle": True},
            "project_description": {"toggle": True},
        }
        for cat, enabled in toggles.items():
            priorities[cat] = {"toggle": enabled}

        return {"version": "4.0", "priorities": priorities}

    async def update_field_priority_config(self, user_id: str, config: dict[str, Any]) -> None:
        try:
            async with self._get_session() as session:
                return await self._update_field_priority_config_impl(session, user_id, config)
        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to update field priority config")
            raise BaseGiljoError(
                message=str(e), context={"operation": "update_field_priority_config", "user_id": user_id}
            ) from e

    async def _update_field_priority_config_impl(
        self, session: AsyncSession, user_id: str, config: dict[str, Any]
    ) -> None:
        priorities = config.get("priorities", config)

        for category, value in priorities.items():
            if isinstance(value, dict):
                if "toggle" not in value or not isinstance(value["toggle"], bool):
                    raise ValidationError(
                        message=f"Invalid toggle config for category '{category}'. Must have boolean 'toggle' key",
                        context={"category": category, "value": value},
                    )
            elif not isinstance(value, bool):
                raise ValidationError(
                    message=f"Invalid value for category '{category}'. Must be bool or dict with 'toggle'",
                    context={"category": category, "value": value},
                )

        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        existing_rows = await self._repo.get_field_priorities(session, user_id, self.tenant_key)
        existing = {row.category: row for row in existing_rows}

        now = datetime.now(UTC)
        for category, value in priorities.items():
            if category not in TOGGLEABLE_CATEGORIES:
                continue

            enabled = value["toggle"] if isinstance(value, dict) else value

            if category in existing:
                existing[category].enabled = enabled
                existing[category].updated_at = now
            else:
                await self._repo.add_field_priority(
                    session,
                    UserFieldPriority(
                        id=str(uuid4()),
                        user_id=user_id,
                        tenant_key=self.tenant_key,
                        category=category,
                        enabled=enabled,
                        created_at=now,
                        updated_at=now,
                    ),
                )

        await session.commit()
        self._logger.info(f"Updated field toggle config for user {user.username}")

        await self._emit_websocket_event(
            event_type="toggle_config_updated",
            data={"user_id": user_id, "toggles": priorities, "version": config.get("version", "4.0")},
        )

    async def reset_field_priority_config(self, user_id: str) -> None:
        try:
            async with self._get_session() as session:
                return await self._reset_field_priority_config_impl(session, user_id)
        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to reset field priority config")
            raise BaseGiljoError(
                message=str(e), context={"operation": "reset_field_priority_config", "user_id": user_id}
            ) from e

    async def _reset_field_priority_config_impl(self, session: AsyncSession, user_id: str) -> None:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        rows = await self._repo.get_field_priorities(session, user_id, self.tenant_key)
        for row in rows:
            await self._repo.delete_field_priority(session, row)

        await session.commit()
        self._logger.info(f"Reset field priority config for user {user.username}")

    async def bulk_disable_field_priority(self, category: str) -> int:
        if category not in TOGGLEABLE_CATEGORIES:
            raise ValidationError(
                message=f"Invalid category '{category}' for bulk disable",
                context={"valid_categories": sorted(TOGGLEABLE_CATEGORIES)},
            )

        try:
            async with self._get_session() as session:
                count = await self._repo.bulk_disable_field_priority(session, self.tenant_key, category)
                if count > 0:
                    self._logger.info(
                        "Bulk-disabled field priority '%s' for %d user(s) in tenant %s",
                        category,
                        count,
                        self.tenant_key,
                    )
                return count
        except (ValidationError, BaseGiljoError):
            raise
        except Exception as e:
            self._logger.exception("Failed to bulk disable field priority")
            raise BaseGiljoError(
                message=str(e), context={"operation": "bulk_disable_field_priority", "category": category}
            ) from e

    async def get_depth_config(self, user_id: str) -> dict[str, Any]:
        try:
            async with self._get_session() as session:
                return await self._get_depth_config_impl(session, user_id)
        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to get depth config")
            raise BaseGiljoError(message=str(e), context={"operation": "get_depth_config", "user_id": user_id}) from e

    async def _get_depth_config_impl(self, session: AsyncSession, user_id: str) -> dict[str, Any]:
        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        return {
            "vision_documents": user.depth_vision_documents,
            "memory_last_n_projects": user.depth_memory_last_n,
            "git_commits": user.depth_git_commits,
            "agent_templates": user.depth_agent_templates,
            "tech_stack_sections": user.depth_tech_stack_sections,
            "architecture_depth": user.depth_architecture,
        }

    async def update_depth_config(self, user_id: str, config: dict[str, Any]) -> None:
        try:
            async with self._get_session() as session:
                return await self._update_depth_config_impl(session, user_id, config)
        except (ResourceNotFoundError, ValidationError, AuthenticationError, AuthorizationError, BaseGiljoError):
            raise
        except (RuntimeError, ValueError) as e:
            self._logger.exception("Failed to update depth config")
            raise BaseGiljoError(
                message=str(e), context={"operation": "update_depth_config", "user_id": user_id}
            ) from e

    async def _update_depth_config_impl(self, session: AsyncSession, user_id: str, config: dict[str, Any]) -> None:
        valid_vision = ["none", "optional", "light", "medium", "full"]
        if "vision_documents" in config and config["vision_documents"] not in valid_vision:
            raise ValidationError(
                message=f"Invalid vision_documents. Must be one of: {', '.join(valid_vision)}",
                context={"vision_documents": config["vision_documents"], "valid_values": valid_vision},
            )

        user = await self._repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        column_map = {
            "vision_documents": "depth_vision_documents",
            "memory_last_n_projects": "depth_memory_last_n",
            "git_commits": "depth_git_commits",
            "agent_templates": "depth_agent_templates",
            "tech_stack_sections": "depth_tech_stack_sections",
            "architecture_depth": "depth_architecture",
        }

        for key, value in config.items():
            col_name = column_map.get(key)
            if col_name:
                setattr(user, col_name, value)

        await session.commit()
        await session.refresh(user)

        self._logger.info(f"Updated depth config for user {user.username}")

        depth_config = {
            "vision_documents": user.depth_vision_documents,
            "memory_last_n_projects": user.depth_memory_last_n,
            "git_commits": user.depth_git_commits,
            "agent_templates": user.depth_agent_templates,
            "tech_stack_sections": user.depth_tech_stack_sections,
            "architecture_depth": user.depth_architecture,
        }
        await self._emit_websocket_event(
            event_type="depth_config_updated", data={"user_id": user_id, "depth_config": depth_config}
        )


    async def _emit_websocket_event(self, event_type: str, data: dict[str, Any]) -> None:
        if not self._websocket_manager:
            self._logger.debug(f"No WebSocket manager available for event: {event_type}")
            return

        try:
            event_data_with_timestamp = {
                **data,
                "tenant_key": self.tenant_key,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=self.tenant_key, event_type=event_type, data=event_data_with_timestamp
            )

            self._logger.debug(f"WebSocket event emitted: {event_type} for tenant {self.tenant_key}")

        except (RuntimeError, ValueError) as e:
            self._logger.warning(f"Failed to emit WebSocket event {event_type}: {e}", exc_info=True)
