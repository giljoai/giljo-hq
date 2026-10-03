# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models.auth import User
from giljo_mcp.models.notifications import (
    VALID_NOTIFICATION_SEVERITIES,
    VALID_NOTIFICATION_SURFACES,
    Notification,
)
from giljo_mcp.schemas.jsonb_validators import validate_notification_payload


logger = logging.getLogger(__name__)


class NotificationService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        websocket_manager=None,
        session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self._websocket_manager = websocket_manager
        self._session = session
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


    async def create(
        self,
        *,
        tenant_key: str,
        notification_type: str,
        severity: str,
        title: str,
        dedupe_key: str,
        body: str | None = None,
        payload: dict | None = None,
        user_id: str | None = None,
        expires_at: datetime | None = None,
        surface: str = "bell",
        role_filter: str | None = None,
        cta_label: str | None = None,
        cta_route: str | None = None,
        dismissible: bool = True,
    ) -> Notification:
        validated_payload = self._validate_fields(notification_type, severity, surface, payload)

        async with self._get_session(tenant_key) as session:
            existing = await self._get_open_by_dedupe(session, tenant_key, dedupe_key)
            if existing is not None:
                return existing

            notification = Notification(
                tenant_key=tenant_key,
                user_id=user_id,
                type=notification_type,
                severity=severity,
                title=title,
                body=body,
                payload=validated_payload,
                dedupe_key=dedupe_key,
                expires_at=expires_at,
                surface=surface,
                role_filter=role_filter,
                cta_label=cta_label,
                cta_route=cta_route,
                dismissible=dismissible,
            )
            session.add(notification)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                existing = await self._get_open_by_dedupe(session, tenant_key, dedupe_key)
                if existing is not None:
                    return existing
                raise

            await session.refresh(notification)
            await session.commit()

        await self._emit_new(tenant_key, notification)
        return notification

    async def upsert_by_dedupe_key(
        self,
        *,
        tenant_key: str,
        notification_type: str,
        severity: str,
        title: str,
        dedupe_key: str,
        body: str | None = None,
        payload: dict | None = None,
        user_id: str | None = None,
        expires_at: datetime | None = None,
        surface: str = "bell",
        role_filter: str | None = None,
        cta_label: str | None = None,
        cta_route: str | None = None,
        dismissible: bool = True,
        resurface_after_hours: int | None = None,
    ) -> Notification:
        validated_payload = self._validate_fields(notification_type, severity, surface, payload)

        async with self._get_session(tenant_key) as session:
            existing = await self._get_open_by_dedupe(session, tenant_key, dedupe_key)
            if existing is not None:
                self._apply_upsert_fields(
                    existing,
                    severity=severity,
                    title=title,
                    body=body,
                    payload=validated_payload,
                    expires_at=expires_at,
                    surface=surface,
                    role_filter=role_filter,
                    cta_label=cta_label,
                    cta_route=cta_route,
                    dismissible=dismissible,
                    resurface_after_hours=resurface_after_hours,
                )
                await session.flush()
                await session.commit()
                await self._emit_updated(tenant_key, existing)
                return existing

            notification = Notification(
                tenant_key=tenant_key,
                user_id=user_id,
                type=notification_type,
                severity=severity,
                title=title,
                body=body,
                payload=validated_payload,
                dedupe_key=dedupe_key,
                expires_at=expires_at,
                surface=surface,
                role_filter=role_filter,
                cta_label=cta_label,
                cta_route=cta_route,
                dismissible=dismissible,
            )
            session.add(notification)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                existing = await self._get_open_by_dedupe(session, tenant_key, dedupe_key)
                if existing is None:
                    raise
                self._apply_upsert_fields(
                    existing,
                    severity=severity,
                    title=title,
                    body=body,
                    payload=validated_payload,
                    expires_at=expires_at,
                    surface=surface,
                    role_filter=role_filter,
                    cta_label=cta_label,
                    cta_route=cta_route,
                    dismissible=dismissible,
                    resurface_after_hours=resurface_after_hours,
                )
                await session.flush()
                await session.commit()
                await self._emit_updated(tenant_key, existing)
                return existing

            await session.refresh(notification)
            await session.commit()

        await self._emit_new(tenant_key, notification)
        return notification

    async def resolve_by_dedupe_key(self, tenant_key: str, dedupe_key: str) -> int:
        now = datetime.now(UTC)
        async with self._get_session(tenant_key) as session:
            stmt = (
                update(Notification)
                .where(
                    Notification.tenant_key == tenant_key,
                    Notification.dedupe_key == dedupe_key,
                    Notification.resolved_at.is_(None),
                )
                .values(resolved_at=now)
                .returning(Notification.id)
            )
            result = await session.execute(stmt)
            resolved_ids = [str(row[0]) for row in result.all()]
            await session.commit()

        if resolved_ids:
            await self._emit_resolved(tenant_key, resolved_ids)
        return len(resolved_ids)

    async def resolve_open_by_type(
        self, tenant_key: str, notification_type: str, *, keep_dedupe_key: str | None = None
    ) -> int:
        now = datetime.now(UTC)
        async with self._get_session(tenant_key) as session:
            stmt = (
                update(Notification)
                .where(
                    Notification.tenant_key == tenant_key,
                    Notification.type == notification_type,
                    Notification.resolved_at.is_(None),
                )
                .values(resolved_at=now)
                .returning(Notification.id)
            )
            if keep_dedupe_key is not None:
                stmt = stmt.where(Notification.dedupe_key != keep_dedupe_key)
            result = await session.execute(stmt)
            resolved_ids = [str(row[0]) for row in result.all()]
            await session.commit()

        if resolved_ids:
            await self._emit_resolved(tenant_key, resolved_ids)
        return len(resolved_ids)

    async def purge_resolved_older_than(
        self, tenant_key: str, retention_days: int, *, now: datetime | None = None
    ) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        async with self._get_session(tenant_key) as session:
            stmt = delete(Notification).where(
                Notification.tenant_key == tenant_key,
                or_(
                    and_(Notification.resolved_at.isnot(None), Notification.resolved_at < cutoff),
                    and_(Notification.expires_at.isnot(None), Notification.expires_at < cutoff),
                ),
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0


    async def list_for_user(
        self,
        tenant_key: str,
        user_id: str,
        include_dismissed: bool = False,
        include_resolved: bool = False,
        surface: str | None = None,
    ) -> list[Notification]:
        async with self._get_session(tenant_key) as session:
            user_role = await self._get_user_role(session, tenant_key, user_id)

            stmt = select(Notification).where(
                Notification.tenant_key == tenant_key,
                (Notification.user_id == user_id) | (Notification.user_id.is_(None)),
                (Notification.role_filter.is_(None)) | (Notification.role_filter == user_role),
            )
            if not include_dismissed:
                stmt = stmt.where(Notification.dismissed_at.is_(None))
            if not include_resolved:
                stmt = stmt.where(Notification.resolved_at.is_(None))
            if surface is not None:
                stmt = stmt.where(Notification.surface.in_((surface, "both")))
            stmt = stmt.order_by(Notification.created_at.desc())

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def mark_read(self, tenant_key: str, notification_id: str, user_id: str) -> Notification:
        return await self._set_timestamp(tenant_key, notification_id, user_id, "read_at")

    async def mark_dismissed(self, tenant_key: str, notification_id: str, user_id: str) -> Notification:
        return await self._set_timestamp(tenant_key, notification_id, user_id, "dismissed_at")


    def _validate_fields(self, notification_type: str, severity: str, surface: str, payload: dict | None) -> dict:
        if severity not in VALID_NOTIFICATION_SEVERITIES:
            raise ValidationError(
                message=f"Invalid notification severity: {severity}",
                context={"severity": severity, "valid": sorted(VALID_NOTIFICATION_SEVERITIES)},
            )
        if surface not in VALID_NOTIFICATION_SURFACES:
            raise ValidationError(
                message=f"Invalid notification surface: {surface}",
                context={"surface": surface, "valid": sorted(VALID_NOTIFICATION_SURFACES)},
            )

        try:
            return validate_notification_payload(notification_type, payload)
        except KeyError as exc:
            raise ValidationError(
                message=f"Unknown notification type (no payload validator): {notification_type}",
                context={"type": notification_type},
            ) from exc
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                message=f"Invalid notification payload for type {notification_type}: {exc!s}",
                context={"type": notification_type},
            ) from exc

    @staticmethod
    def _apply_upsert_fields(
        notification: Notification,
        *,
        severity: str,
        title: str,
        body: str | None,
        payload: dict,
        expires_at: datetime | None,
        surface: str,
        role_filter: str | None,
        cta_label: str | None,
        cta_route: str | None,
        dismissible: bool,
        resurface_after_hours: int | None = None,
    ) -> None:
        notification.severity = severity
        notification.title = title
        notification.body = body
        notification.payload = payload
        notification.expires_at = expires_at
        notification.surface = surface
        notification.role_filter = role_filter
        notification.cta_label = cta_label
        notification.cta_route = cta_route
        notification.dismissible = dismissible

        if (
            resurface_after_hours is not None
            and notification.dismissed_at is not None
            and notification.dismissed_at < datetime.now(UTC) - timedelta(hours=resurface_after_hours)
        ):
            notification.dismissed_at = None

    async def _get_user_role(self, session: AsyncSession, tenant_key: str, user_id: str) -> str | None:
        stmt = select(User.role).where(User.tenant_key == tenant_key, User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_open_by_dedupe(self, session: AsyncSession, tenant_key: str, dedupe_key: str) -> Notification | None:
        stmt = select(Notification).where(
            Notification.tenant_key == tenant_key,
            Notification.dedupe_key == dedupe_key,
            Notification.resolved_at.is_(None),
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def _set_timestamp(self, tenant_key: str, notification_id: str, user_id: str, column: str) -> Notification:
        now = datetime.now(UTC)
        async with self._get_session(tenant_key) as session:
            stmt = select(Notification).where(
                Notification.tenant_key == tenant_key,
                Notification.id == notification_id,
                (Notification.user_id == user_id) | (Notification.user_id.is_(None)),
            )
            result = await session.execute(stmt)
            notification = result.scalars().first()
            if notification is None:
                raise ResourceNotFoundError(
                    message="Notification not found or access denied",
                    context={"notification_id": notification_id, "user_id": user_id},
                )

            setattr(notification, column, now)
            await session.flush()
            await session.commit()
            return notification

    async def _emit_new(self, tenant_key: str, notification: Notification) -> None:
        if not self._websocket_manager:
            self._logger.debug("No WebSocket manager available for notification:new")
            return

        payload_dict = notification.payload if isinstance(notification.payload, dict) else {}
        await self._websocket_manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="notification:new",
            data={
                "id": str(notification.id),
                "user_id": notification.user_id,
                "type": notification.type,
                "severity": notification.severity,
                "title": notification.title,
                "body": notification.body,
                "payload": notification.payload,
                "project_id": payload_dict.get("project_id"),
                "product_id": payload_dict.get("product_id"),
                "surface": notification.surface,
                "role_filter": notification.role_filter,
                "cta_label": notification.cta_label,
                "cta_route": notification.cta_route,
                "dismissible": notification.dismissible,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            },
        )

    async def _emit_updated(self, tenant_key: str, notification: Notification) -> None:
        if not self._websocket_manager:
            self._logger.debug("No WebSocket manager available for notification:updated")
            return

        await self._websocket_manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="notification:updated",
            data={
                "id": str(notification.id),
                "user_id": notification.user_id,
                "type": notification.type,
                "severity": notification.severity,
                "title": notification.title,
                "body": notification.body,
                "payload": notification.payload,
                "surface": notification.surface,
                "role_filter": notification.role_filter,
                "cta_label": notification.cta_label,
                "cta_route": notification.cta_route,
                "dismissible": notification.dismissible,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            },
        )

    async def _emit_resolved(self, tenant_key: str, notification_ids: list[str]) -> None:
        if not self._websocket_manager or not notification_ids:
            self._logger.debug("No WebSocket manager available for notification:resolved")
            return

        await self._websocket_manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="notification:resolved",
            data={"ids": notification_ids},
        )
