# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""NotificationService — DB-backed notification lifecycle (IMP-5037a Phase 1).

The owning service for the ``notifications`` table. Every write to a
Notification routes through here; tools/endpoints/other services never
``setattr`` notification rows directly.

Design (mirrors AuthService):
- Async SQLAlchemy 2.0; request-scoped instance.
- Optional injected ``session`` for test transaction isolation.
- Exception-based error handling (never returns ``{"success": False}``).
- Every query filters by ``tenant_key`` — no exceptions.
- Field-allowlisted create (explicit kwargs, not ``hasattr``); payload JSONB
  validated by the type-keyed registry in ``jsonb_validators``.
- Emit-time de-dupe enforced by the ``(tenant_key, dedupe_key) WHERE
  resolved_at IS NULL`` partial unique index: ``create`` returns the existing
  open row instead of inserting a duplicate.
"""

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
    """Service for creating and managing tenant-scoped notifications.

    Thread Safety: request-scoped. Do not share across requests.

    TRANSACTION CONTRACT (BE-6036 / BE-6037): the write methods (``create``,
    ``upsert_by_dedupe_key``, ``resolve_by_dedupe_key``) COMMIT INTERNALLY on
    their own session. Do NOT call them inside a caller-managed transaction
    (``async with session.begin(): ...``) that you expect to stay open: the
    internal commit closes that transaction and the next statement then raises
    "Can't operate on closed transaction inside context manager". Give the
    service its own session (the default ``_get_session`` path) or call it
    OUTSIDE your ``begin()`` block. This trap is why the trial reaper banner-sync
    runs on a fresh, unwrapped session (see ``saas/trial/reaper.py``, BE-6036).
    """

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
        """Return a session, preferring an injected test session when present."""
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

    # ========================================================================
    # Write boundary
    # ========================================================================

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
        """Create a notification, de-duplicating against open rows.

        If an OPEN (``resolved_at IS NULL``) notification already exists for
        ``(tenant_key, dedupe_key)``, this is a no-op and the existing row is
        returned UNCHANGED (its payload/severity/title are NOT updated). Use
        ``upsert_by_dedupe_key`` for the present-or-not scanner path that must
        refresh an existing open row. The ``payload`` is validated by the
        type-keyed JSONB registry before persistence.

        Args:
            notification_type: the ``Notification.type`` discriminator (e.g.
                ``api_key.expiring_soon``); keys the payload validator.
            surface: render surface — ``bell`` | ``banner`` | ``both``.
            role_filter: when set, only users holding this role see the row
                (server-enforced in ``list_for_user``).
            cta_label / cta_route: optional call-to-action label + NAMED Vue
                route string (NOT a URL).
            dismissible: whether the user may dismiss the row.

        Raises:
            ValidationError: invalid ``severity`` / ``surface`` enum, or payload
                shape mismatch / unknown ``notification_type`` from the JSONB
                validator.
        """
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
                # Lost a race on the partial unique index — fall back to the
                # existing open row (de-dupe semantics hold under concurrency).
                await session.rollback()
                existing = await self._get_open_by_dedupe(session, tenant_key, dedupe_key)
                if existing is not None:
                    return existing
                raise

            # Load server defaults (created_at) before committing — sessions use
            # expire_on_commit=False, so attributes stay accessible afterward.
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
        """Present-or-not idempotent upsert for scanners.

        If an OPEN (``resolved_at IS NULL``) row exists for
        ``(tenant_key, dedupe_key)``, UPDATE its payload, severity, title, body,
        surface, role_filter, cta_* and dismissible in place and return it.
        Otherwise CREATE a new row. This is the path background scanners use to
        keep a banner's content current (e.g. ``5 pending migrations`` →
        ``3 pending migrations``); ``create`` is NOT a substitute because it
        never mutates an existing open row.

        ``resurface_after_hours``: when set, a re-emit against an existing open
        row whose ``dismissed_at`` is older than that many hours clears
        ``dismissed_at`` so the still-true condition resurfaces (daily-resurface
        for persistent banners like skills drift). A row dismissed more recently
        than the window is left dismissed.

        Transaction-safe under the partial unique index: an insert that loses
        the race falls back to updating the now-existing open row.

        Raises:
            ValidationError: same validation contract as ``create``.
        """
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
                # Lost the insert race — update the row the winner created.
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
        """Mark all open notifications for ``(tenant_key, dedupe_key)`` resolved.

        Auto-clear hook: e.g. when the underlying API key is regenerated or
        revoked, its expiry notification is resolved. Returns the number of
        rows resolved (0 if none were open).

        D16 (Headless S3d): resolving a row used to emit no event at all, so a
        banner whose underlying condition already cleared (an answered agent
        question, a fixed pending-migrations count) stayed on screen until the
        next full page load. The resolved ids are broadcast as
        ``notification:resolved`` so the store can drop them live.
        """
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
        """Resolve all open notifications of ``notification_type`` for the tenant.

        Used by banner emitters whose ``dedupe_key`` is per-version (e.g.
        ``system.update_available:{tag}``): when the condition clears, or a newer
        version supersedes an older one, every stale open row of the type is
        resolved. Pass ``keep_dedupe_key`` to spare the row that is still
        current (the one the emitter just upserted). Returns rows resolved.
        """
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
        """Delete SAFELY-purgeable notifications for a tenant past retention.

        Retention valve (BE-3011): the ``notifications`` table had no purge path
        and grew unbounded per tenant. A row is eligible ONLY when its underlying
        condition is already closed and older than the retention window:

        - it was RESOLVED (``resolved_at``) more than ``retention_days`` ago, OR
        - it EXPIRED (``expires_at``) more than ``retention_days`` ago.

        Active / unresolved notifications are NEVER deleted by age alone — they
        survive until something resolves them. Tenant-scoped: only this tenant's
        rows are ever in scope (the caller enumerates tenants), so one tenant's
        purge can never touch another tenant's rows. Commits on its own session.

        Returns:
            int: number of rows deleted (0 if none were eligible).
        """
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

    # ========================================================================
    # Read / per-user lifecycle
    # ========================================================================

    async def list_for_user(
        self,
        tenant_key: str,
        user_id: str,
        include_dismissed: bool = False,
        include_resolved: bool = False,
        surface: str | None = None,
    ) -> list[Notification]:
        """List notifications visible to a user, newest-first.

        Visible = rows scoped to this user (``user_id``) plus tenant-scoped rows
        (``user_id IS NULL``). Dismissed/resolved rows are excluded unless the
        corresponding include flag is set.

        ``surface`` filters to rows that render on a given surface: passing
        ``"banner"`` returns rows whose ``surface`` is ``banner`` OR ``both``
        (likewise ``"bell"`` returns ``bell`` OR ``both``). Omit for all.

        Role gate (server-enforced): rows with a non-NULL ``role_filter`` are
        excluded unless the requesting user holds that role. This is NOT a
        frontend-only filter — the user's role is fetched from the DB.
        """
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
        """Set ``read_at`` on a notification owned-by or visible-to the user."""
        return await self._set_timestamp(tenant_key, notification_id, user_id, "read_at")

    async def mark_dismissed(self, tenant_key: str, notification_id: str, user_id: str) -> Notification:
        """Set ``dismissed_at`` on a notification owned-by or visible-to the user."""
        return await self._set_timestamp(tenant_key, notification_id, user_id, "dismissed_at")

    # ========================================================================
    # Private helpers
    # ========================================================================

    def _validate_fields(self, notification_type: str, severity: str, surface: str, payload: dict | None) -> dict:
        """Validate severity + surface enums and the type-keyed payload schema."""
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
        """Refresh the mutable presentation fields of an existing open row.

        When ``resurface_after_hours`` is set and the row was dismissed longer
        ago than that window, ``dismissed_at`` is cleared so the still-true
        condition re-appears (daily-resurface). A more-recent dismissal is left
        intact.
        """
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
        """Return the requesting user's role (tenant-scoped), or None if absent."""
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
        """Emit a ``notification:new`` WS event to the tenant (graceful no-op)."""
        if not self._websocket_manager:
            self._logger.debug("No WebSocket manager available for notification:new")
            return

        try:
            # BE-9525c: top-level project_id/product_id on the envelope so every
            # reader (FE router, notificationRouting.js, clearForProject) can key
            # on ONE shape instead of reaching into free-form payload/metadata --
            # additive, derived from whatever the row's own payload already
            # carries (never invented). Legacy rows with neither key simply get
            # None here; readers still fall back to payload/metadata.
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
        except (RuntimeError, ValueError) as exc:
            self._logger.warning("Failed to emit notification:new WS event: %s", exc, exc_info=True)

    async def _emit_updated(self, tenant_key: str, notification: Notification) -> None:
        """Emit a ``notification:updated`` WS event (graceful no-op).

        D16: fired when ``upsert_by_dedupe_key`` refreshes an already-open row
        in place (e.g. a scanner's "5 pending migrations" → "3 pending
        migrations"). Same payload shape as ``notification:new`` so a single
        client handler can normalize either into the store.
        """
        if not self._websocket_manager:
            self._logger.debug("No WebSocket manager available for notification:updated")
            return

        try:
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
        except (RuntimeError, ValueError) as exc:
            self._logger.warning("Failed to emit notification:updated WS event: %s", exc, exc_info=True)

    async def _emit_resolved(self, tenant_key: str, notification_ids: list[str]) -> None:
        """Emit a ``notification:resolved`` WS event (graceful no-op).

        D16: the fix for the durable "answered question stays on screen" bug —
        ``resolve_by_dedupe_key``/``resolve_open_by_type`` used to be silent, so
        the store never learned a row's underlying condition had cleared until
        the next full page load. Carries just the resolved ids; the client
        drops them from its local notification list.
        """
        if not self._websocket_manager or not notification_ids:
            self._logger.debug("No WebSocket manager available for notification:resolved")
            return

        try:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=tenant_key,
                event_type="notification:resolved",
                data={"ids": notification_ids},
            )
        except (RuntimeError, ValueError) as exc:
            self._logger.warning("Failed to emit notification:resolved WS event: %s", exc, exc_info=True)
