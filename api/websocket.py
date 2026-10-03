# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
import websockets.exceptions
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.exceptions import WebSocketException

from api.broker.base import WebSocketBrokerMessage, WebSocketEventBroker
from giljo_mcp.events.schemas import EventFactory, bound_event_message
from giljo_mcp.logging import ErrorCode
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

_WS_SEND_TIMEOUT_SECONDS = 5
_MAX_CLIENT_ID_LENGTH = 128


class WebSocketManager:

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.auth_contexts: dict[str, dict[str, Any]] = {}
        self.tenant_connections: dict[str, set[str]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._event_broker: WebSocketEventBroker | None = None
        self._broker_unsubscribe = None
        self._broker_origin = uuid4().hex
        self._publish_to_broker_enabled = False

    def attach_broker(self, broker: WebSocketEventBroker) -> None:
        if self._broker_unsubscribe:
            try:
                self._broker_unsubscribe()
            except (RuntimeError, OSError):
                logger.debug("Failed unsubscribing broker handler", exc_info=True)
            self._broker_unsubscribe = None

        self._event_broker = broker

        from api.startup.database import _worker_count

        self._publish_to_broker_enabled = _worker_count() > 1

        async def _handle(message: WebSocketBrokerMessage) -> None:
            if message.origin and message.origin == self._broker_origin:
                return

            if message.control == "disconnect_tenant":
                await self.disconnect_tenant(message.tenant_key, publish_to_broker=False)
                return

            if message.control:
                return

            await self.broadcast_event_to_tenant(
                tenant_key=message.tenant_key,
                event=message.event,
                exclude_client=message.exclude_client,
                publish_to_broker=False,
            )

        self._broker_unsubscribe = broker.subscribe(_handle)

    @staticmethod
    def _unwrap_websocket_connection(connection: Any) -> Any:
        websocket = getattr(connection, "websocket", None)
        if isinstance(websocket, WebSocket):
            return websocket
        return connection


    def _index_tenant_connection(self, client_id: str, tenant_key: str | None) -> None:
        if tenant_key:
            self.tenant_connections.setdefault(tenant_key, set()).add(client_id)

    def _deindex_tenant_connection(self, client_id: str, tenant_key: str | None) -> None:
        if tenant_key:
            bucket = self.tenant_connections.get(tenant_key)
            if bucket is not None:
                bucket.discard(client_id)
                if not bucket:
                    del self.tenant_connections[tenant_key]
            return
        empty_keys = []
        for key, bucket in self.tenant_connections.items():
            bucket.discard(client_id)
            if not bucket:
                empty_keys.append(key)
        for key in empty_keys:
            del self.tenant_connections[key]


    def schedule(self, coro: Any) -> None:
        task = asyncio.create_task(self._run_scheduled(coro))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    @staticmethod
    async def _run_scheduled(coro: Any) -> None:
        try:
            await coro
        except Exception:
            logger.exception(
                "scheduled_websocket_broadcast_failed error_code=%s",
                ErrorCode.WS_BROADCAST_FAILED.value,
            )

    async def broadcast_event_to_tenant(
        self,
        tenant_key: str,
        event: dict[str, Any],
        exclude_client: str | None = None,
        *,
        publish_to_broker: bool = True,
    ) -> int:
        if not tenant_key:
            raise ValueError("tenant_key cannot be empty")

        if not isinstance(event, dict):
            raise TypeError("event must be a dictionary")

        event_type = event.get("type")
        if not event_type:
            raise ValueError("event.type cannot be empty")

        data = event.get("data") or {}
        if not isinstance(data, dict):
            raise TypeError("event.data must be a dictionary")

        if "tenant_key" not in data:
            data = {**data, "tenant_key": tenant_key}
        elif data.get("tenant_key") != tenant_key:
            raise ValueError("event.data.tenant_key must match tenant_key")

        message = {
            "type": event_type,
            "timestamp": event.get("timestamp") or datetime.now(UTC).isoformat(),
            "schema_version": event.get("schema_version") or "1.0",
            "data": data,
        }

        payload = json.dumps(bound_event_message(message))

        target_client_ids = [
            client_id for client_id in self.tenant_connections.get(tenant_key, set()) if client_id != exclude_client
        ]

        async def _send_to_client(client_id: str) -> tuple[str, bool]:
            connection = self.active_connections.get(client_id)
            if connection is None:
                return (client_id, False)
            websocket = self._unwrap_websocket_connection(connection)
            try:
                await asyncio.wait_for(websocket.send_text(payload), timeout=_WS_SEND_TIMEOUT_SECONDS)
                return (client_id, True)
            except (RuntimeError, ValueError, KeyError, TimeoutError, OSError, WebSocketDisconnect) as e:
                logger.warning(
                    "websocket_send_failed error_code=%s client_id=%s tenant_key=%s event_type=%s error_message=%s",
                    ErrorCode.WS_MESSAGE_SEND_FAILED.value,
                    client_id,
                    tenant_key,
                    event_type,
                    str(e),
                )
                return (client_id, False)

        results = await asyncio.gather(*[_send_to_client(client_id) for client_id in target_client_ids])

        sent_count = 0
        failed_count = 0
        disconnected_clients: list[str] = []
        for client_id, ok in results:
            if ok:
                sent_count += 1
            else:
                failed_count += 1
                disconnected_clients.append(client_id)

        for client_id in disconnected_clients:
            self.disconnect(client_id)

        if publish_to_broker and self._event_broker and self._publish_to_broker_enabled:
            try:
                await self._event_broker.publish(
                    WebSocketBrokerMessage(
                        tenant_key=tenant_key,
                        event=message,
                        exclude_client=exclude_client,
                        origin=self._broker_origin,
                    )
                )
            except (RuntimeError, ValueError, KeyError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
                logger.warning(
                    "websocket_broker_publish_failed error_code=%s tenant_key=%s event_type=%s error_message=%s",
                    ErrorCode.WS_BROADCAST_FAILED.value,
                    tenant_key,
                    event_type,
                    str(e),
                )

        logger.info(
            f"WebSocket broadcast to tenant completed: {sent_count} sent, {failed_count} failed",
            extra={
                "tenant_key": tenant_key,
                "event_type": event_type,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "total_clients": len(target_client_ids),
                "exclude_client": exclude_client,
            },
        )

        return sent_count

    async def disconnect_tenant(
        self, tenant_key: str, *, reason: str = "account deactivated", publish_to_broker: bool = True
    ) -> int:
        from api.ws_revocation import close_tenant_sockets

        return await close_tenant_sockets(self, tenant_key, reason=reason, publish_to_broker=publish_to_broker)

    async def connect(self, websocket: WebSocket, client_id: str, auth_context: dict[str, Any] | None = None):
        if len(client_id) > _MAX_CLIENT_ID_LENGTH:
            raise WebSocketException(code=1008, reason="Invalid client id")
        existing = self.active_connections.get(client_id)
        new_tenant = (auth_context or {}).get("tenant_key")
        if existing is not None and self.auth_contexts.get(client_id, {}).get("tenant_key") != new_tenant:
            raise WebSocketException(code=1008, reason="Client id in use")

        self.active_connections[client_id] = websocket
        self.auth_contexts[client_id] = auth_context or {}

        self._index_tenant_connection(client_id, new_tenant)

        if existing is not None and self._unwrap_websocket_connection(existing) is not websocket:
            logger.info("Superseding pre-existing WebSocket for client_id=%s on reconnect", client_id)
            try:
                await self._unwrap_websocket_connection(existing).close(
                    code=1012, reason="Superseded by new connection"
                )
            except (RuntimeError, OSError):
                logger.debug("Failed closing superseded WebSocket for client_id=%s", client_id, exc_info=True)

        auth_type = auth_context.get("auth_type", "none") if auth_context else "none"
        logger.info(f"WebSocket connected: {client_id} (auth_type: {auth_type})")

    def disconnect(self, client_id: str, websocket: WebSocket | None = None):
        if websocket is not None:
            current = self.active_connections.get(client_id)
            if current is not None and self._unwrap_websocket_connection(current) is not websocket:
                logger.debug("Skipping stale WebSocket disconnect for client_id=%s (superseded)", client_id)
                return

        self._deindex_tenant_connection(client_id, self.auth_contexts.get(client_id, {}).get("tenant_key"))

        if client_id in self.active_connections:
            del self.active_connections[client_id]

        if client_id in self.auth_contexts:
            del self.auth_contexts[client_id]

        logger.info(f"WebSocket disconnected: {client_id}")

    async def send_json(self, data: dict, client_id: str):
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(data)
            except Exception as _exc:
                logger.exception(
                    "websocket_send_json_error error_code=%s client_id=%s",
                    ErrorCode.WS_MESSAGE_SEND_FAILED.value,
                    client_id,
                )
                self.disconnect(client_id)

    async def broadcast(self, message: str):
        disconnected = []
        for client_id, websocket in list(self.active_connections.items()):
            try:
                await asyncio.wait_for(websocket.send_text(message), timeout=_WS_SEND_TIMEOUT_SECONDS)
            except Exception as _exc:
                logger.exception(
                    "websocket_broadcast_error error_code=%s client_id=%s",
                    ErrorCode.WS_BROADCAST_FAILED.value,
                    client_id,
                )
                disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect(client_id)

    async def broadcast_json(self, data: dict):
        message = json.dumps(data)
        await self.broadcast(message)

    async def broadcast_to_tenant(
        self,
        tenant_key: str,
        event_type: str,
        data: dict[str, Any],
        schema_version: str = "1.0",
        exclude_client: str | None = None,
    ) -> int:
        if not tenant_key:
            raise ValueError("tenant_key cannot be empty")

        if not event_type:
            raise ValueError("event_type cannot be empty")

        event = EventFactory.tenant_envelope(
            event_type=event_type,
            tenant_key=tenant_key,
            data=data,
            schema_version=schema_version,
        )

        return await self.broadcast_event_to_tenant(
            tenant_key=tenant_key,
            event=event,
            exclude_client=exclude_client,
        )

    def get_connection_count(self) -> int:
        return len(self.active_connections)



    async def broadcast_project_update(
        self,
        project_id: str,
        update_type: str,
        project_data: dict,
        tenant_key: str | None = None,
    ):
        if not tenant_key:
            from giljo_mcp.tenant import TenantManager

            tenant_key = TenantManager.get_current_tenant()
        if not tenant_key:
            logger.warning("broadcast_project_update: no tenant_key available for project %s", sanitize(project_id))
            return

        await self.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="project_update",
            data={
                "project_id": project_id,
                "update_type": update_type,
                "name": project_data.get("name"),
                "description": project_data.get("description"),
                "status": project_data.get("status"),
                "mission": project_data.get("mission"),
                "product_id": project_data.get("product_id"),
            },
        )


    async def start_heartbeat(self, interval: int = 30):
        while True:
            await asyncio.sleep(interval)
            try:
                await self.send_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Heartbeat cycle failed; continuing")

    async def send_heartbeat(self):
        heartbeat = {"type": "ping", "timestamp": datetime.now(UTC).isoformat()}

        disconnected = []
        for client_id, websocket in list(self.active_connections.items()):
            try:
                await asyncio.wait_for(websocket.send_json(heartbeat), timeout=_WS_SEND_TIMEOUT_SECONDS)
            except (
                RuntimeError,
                OSError,
                TimeoutError,
                WebSocketDisconnect,
                websockets.exceptions.ConnectionClosed,
            ) as e:
                logger.debug(f"Heartbeat failed for {client_id}: {e}")
                disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect(client_id)
            logger.info(f"Removed inactive connection: {client_id}")


    async def broadcast_job_status_update(
        self,
        job_id: str,
        agent_display_name: str,
        tenant_key: str,
        old_status: str,
        new_status: str,
        *,
        updated_at: datetime | None = None,
        duration_seconds: float | None = None,
        project_id: str | None = None,
        product_id: str | None = None,
    ):
        event_type = "agent:status_changed"

        message_data: dict[str, Any] = {
            "job_id": job_id,
            "agent_display_name": agent_display_name,
            "old_status": old_status,
            "status": new_status,
            "tenant_key": tenant_key,
            "updated_at": (updated_at or datetime.now(UTC)).isoformat(),
        }

        if project_id is not None:
            message_data["project_id"] = project_id

        if product_id is not None:
            message_data["product_id"] = product_id
        if duration_seconds is not None:
            message_data["duration_seconds"] = duration_seconds

        event = EventFactory.tenant_envelope(
            event_type=event_type,
            tenant_key=tenant_key,
            data=message_data,
            schema_version="1.0",
        )

        await self.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

        logger.info(f"Broadcast {event_type} - {job_id} ({old_status} -> {new_status}, project: {project_id})")


