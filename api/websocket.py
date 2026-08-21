# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
WebSocket manager for real-time updates
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
import websockets.exceptions
from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from api.auth_utils import check_subscription_permission
from api.broker.base import WebSocketBrokerMessage, WebSocketEventBroker
from giljo_mcp.events.schemas import EventFactory, bound_event_message
from giljo_mcp.logging import ErrorCode
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

# BE-3008a: per-client send timeout. A wedged client must not hang the fan-out
# loop, so every send is bounded; on timeout the client is dropped.
_WS_SEND_TIMEOUT_SECONDS = 5


class WebSocketManager:
    """Manages WebSocket connections and subscriptions with authentication"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.auth_contexts: dict[str, dict[str, Any]] = {}  # client_id -> auth context
        self.subscriptions: dict[str, set[str]] = {}  # client_id -> set of subscriptions
        self.entity_subscribers: dict[str, set[str]] = {}  # entity_key -> set of client_ids
        # BE-3008b: tenant_key -> set of client_ids. Lets the tenant fan-out iterate
        # ONLY the target tenant's sockets (O(tenant)), not every connection.
        # Maintained in connect()/disconnect().
        self.tenant_connections: dict[str, set[str]] = {}
        # BE-3008b: strong refs to in-flight fire-and-forget broadcast tasks so the
        # event loop does not GC them mid-send. Drained via done-callback.
        self._background_tasks: set[asyncio.Task] = set()
        self._event_broker: WebSocketEventBroker | None = None
        self._broker_unsubscribe = None
        self._broker_origin = uuid4().hex
        # m15: single worker => the cross-worker pg_notify publish is pure overhead
        # (the sole listener is THIS worker, which discards its own echo). Resolved
        # once at attach_broker() time and cached off the hot broadcast path.
        self._publish_to_broker_enabled = False

    def attach_broker(self, broker: WebSocketEventBroker) -> None:
        if self._broker_unsubscribe:
            try:
                self._broker_unsubscribe()
            except (RuntimeError, OSError):
                logger.debug("Failed unsubscribing broker handler", exc_info=True)
            self._broker_unsubscribe = None

        self._event_broker = broker

        # m15: cache the single-vs-multi-worker decision once (local import avoids
        # the core_services -> websocket circular import).
        from api.startup.database import _worker_count

        self._publish_to_broker_enabled = _worker_count() > 1

        async def _handle(message: WebSocketBrokerMessage) -> None:
            # Avoid echo: the publishing worker already handled it locally.
            if message.origin and message.origin == self._broker_origin:
                return

            # TSK-9006: a control message closes this worker's tenant sockets
            # (deactivation must bite on every worker); publish_to_broker=False
            # so a peer's fan-out does not re-publish and loop.
            if message.control == "disconnect_tenant":
                await self.disconnect_tenant(message.tenant_key, publish_to_broker=False)
                return

            # BE-9296a: a control message is NOT an event — its ``event`` is an empty
            # envelope by design (see WebSocketBrokerMessage). Falling through would
            # fan a control frame out to every browser as if it were a real update.
            # Today ``disconnect_tenant`` is handled above and nothing else sets
            # ``control``, so this changes no existing behavior; it makes the
            # channel's own stated contract enforced rather than assumed, which is
            # what lets a second control type share the channel safely.
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

    # BE-3008b: tenant-index maintenance -------------------------------------

    def _index_tenant_connection(self, client_id: str, tenant_key: str | None) -> None:
        """Register ``client_id`` under ``tenant_key`` in the fan-out index.

        Connections with no tenant_key (e.g. the pre-auth setup-context socket)
        are intentionally NOT indexed — they never receive tenant broadcasts.
        """
        if tenant_key:
            self.tenant_connections.setdefault(tenant_key, set()).add(client_id)

    def _deindex_tenant_connection(self, client_id: str, tenant_key: str | None) -> None:
        """Remove ``client_id`` from the tenant index.

        When ``tenant_key`` is known the lookup is O(1); when it is unknown the
        client is scrubbed from every bucket defensively so a stale id can never
        keep receiving a tenant's fan-out.
        """
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

    # BE-3008b: fire-and-forget broadcast scheduling -------------------------

    def schedule(self, coro: Any) -> None:
        """Run an awaitable as a tracked, fire-and-forget background task.

        Decouples a caller's write path from WebSocket fan-out latency: the
        write returns immediately while delivery to (possibly slow) clients
        happens off the request path. Exceptions are logged, never propagated.
        Use AFTER ``session.commit()`` so a rolled-back write can never produce
        a phantom client-side event.
        """
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
        """Broadcast a canonical event envelope to all clients in a tenant."""
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

        # BE-3008b: serialize ONCE for the whole fan-out (send_json would re-encode
        # per recipient). BE-9416 bounds in place first, so BOTH legs carry one payload.
        payload = json.dumps(bound_event_message(message))

        # BE-3008b: iterate ONLY this tenant's sockets via the tenant index
        # (O(tenant)), not every connection. Snapshot to a list so a concurrent
        # (dis)connect can't mutate the set under the gather.
        target_client_ids = [
            client_id for client_id in self.tenant_connections.get(tenant_key, set()) if client_id != exclude_client
        ]

        async def _send_to_client(client_id: str) -> tuple[str, bool]:
            connection = self.active_connections.get(client_id)
            if connection is None:
                return (client_id, False)
            websocket = self._unwrap_websocket_connection(connection)
            try:
                # BE-6072 (F4): bound the per-client send so a wedged client is
                # evicted, not waited on. send_text delivers the pre-serialized
                # payload (BE-3008b serialize-once).
                await asyncio.wait_for(websocket.send_text(payload), timeout=_WS_SEND_TIMEOUT_SECONDS)
                return (client_id, True)
            except (RuntimeError, ValueError, KeyError, TimeoutError, OSError) as e:
                logger.warning(
                    "websocket_send_failed error_code=%s client_id=%s tenant_key=%s event_type=%s error_message=%s",
                    ErrorCode.WS_MESSAGE_SEND_FAILED.value,
                    client_id,
                    tenant_key,
                    event_type,
                    str(e),
                )
                return (client_id, False)

        # BE-3008b: fan out CONCURRENTLY so a wedged client's bounded timeout runs
        # alongside the fast sends (a sequential loop gave each stalled socket
        # _WS_SEND_TIMEOUT_SECONDS of head-of-line latency for every later peer).
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
            except (RuntimeError, ValueError, KeyError, asyncpg.PostgresError) as e:
                # BE-6072 (m15): asyncpg.PostgresError covers the pg_notify ~8000-byte
                # payload limit. Local delivery already happened, so swallow + log.
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
        """Force-close a tenant's live sockets on user deactivation (TSK-9006).

        Thin delegate: the body lives in ws_revocation.close_tenant_sockets,
        extracted so this at-budget file does not grow. Returns sockets closed.
        """
        from api.ws_revocation import close_tenant_sockets

        return await close_tenant_sockets(self, tenant_key, reason=reason, publish_to_broker=publish_to_broker)

    async def connect(self, websocket: WebSocket, client_id: str, auth_context: dict[str, Any] | None = None):
        """Accept and track a new WebSocket connection (accept() runs in the endpoint)."""
        # Evict any pre-existing socket on this client_id: a reused id would otherwise
        # leave two live sockets on one key (frontend mints fresh ids; CLI/API-key clients may reuse one).
        existing = self.active_connections.get(client_id)

        # SEC-9171 (#24): a reused id switching TENANTS must leave the old tenant's
        # fan-out bucket, or tenant A's broadcasts keep reaching tenant B's socket.
        old_tenant = self.auth_contexts.get(client_id, {}).get("tenant_key")
        if old_tenant and old_tenant != (auth_context or {}).get("tenant_key"):
            self._deindex_tenant_connection(client_id, old_tenant)

        self.active_connections[client_id] = websocket
        self.auth_contexts[client_id] = auth_context or {}  # Store auth context
        self.subscriptions[client_id] = set()

        # BE-3008b: tenant fan-out index (same-id reconnect = idempotent set add).
        self._index_tenant_connection(client_id, (auth_context or {}).get("tenant_key"))

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
        """Remove WebSocket connection and clean up subscriptions.

        Identity-safe: when ``websocket`` is provided, the entry is removed only if
        it is STILL the socket registered for ``client_id`` — stopping a stale
        socket's teardown from evicting a newer live socket on the same id. Internal
        send-failure cleanup passes no websocket and removes by id.
        """
        if websocket is not None:
            current = self.active_connections.get(client_id)
            if current is not None and self._unwrap_websocket_connection(current) is not websocket:
                # A newer socket already owns this client_id — leave it alone.
                logger.debug("Skipping stale WebSocket disconnect for client_id=%s (superseded)", client_id)
                return

        # BE-3008b: drop from the tenant fan-out index BEFORE deleting the auth
        # context (the tenant_key is resolved from it).
        self._deindex_tenant_connection(client_id, self.auth_contexts.get(client_id, {}).get("tenant_key"))

        if client_id in self.active_connections:
            del self.active_connections[client_id]

        if client_id in self.auth_contexts:
            del self.auth_contexts[client_id]

        # Clean up subscriptions
        if client_id in self.subscriptions:
            for entity_key in self.subscriptions[client_id]:
                if entity_key in self.entity_subscribers:
                    self.entity_subscribers[entity_key].discard(client_id)
                    if not self.entity_subscribers[entity_key]:
                        del self.entity_subscribers[entity_key]
            del self.subscriptions[client_id]

        logger.info(f"WebSocket disconnected: {client_id}")

    async def subscribe(self, client_id: str, entity_type: str, entity_id: str, tenant_key: str | None = None):
        """Subscribe client to entity updates with authorization check"""

        # Check authorization
        auth_context = self.auth_contexts.get(client_id, {})
        if not check_subscription_permission(auth_context, entity_type, entity_id, tenant_key):
            logger.warning(
                "unauthorized_subscription_attempt error_code=%s client_id=%s entity_type=%s entity_id=%s tenant_key=%s",
                ErrorCode.WS_AUTHENTICATION_FAILED.value,
                client_id,
                entity_type,
                entity_id,
                tenant_key,
            )
            raise HTTPException(status_code=403, detail="Not authorized to subscribe to this entity")

        entity_key = f"{entity_type}:{entity_id}"

        # Track subscription for client
        if client_id in self.subscriptions:
            self.subscriptions[client_id].add(entity_key)

        # Track subscribers for entity
        if entity_key not in self.entity_subscribers:
            self.entity_subscribers[entity_key] = set()
        self.entity_subscribers[entity_key].add(client_id)

        logger.debug(f"Client {client_id} subscribed to {entity_key}")

    async def unsubscribe(self, client_id: str, entity_type: str, entity_id: str):
        """Unsubscribe client from entity updates"""
        entity_key = f"{entity_type}:{entity_id}"

        # Remove subscription for client
        if client_id in self.subscriptions:
            self.subscriptions[client_id].discard(entity_key)

        # Remove subscriber from entity
        if entity_key in self.entity_subscribers:
            self.entity_subscribers[entity_key].discard(client_id)
            if not self.entity_subscribers[entity_key]:
                del self.entity_subscribers[entity_key]

        logger.debug(f"Client {client_id} unsubscribed from {entity_key}")

    async def send_json(self, data: dict, client_id: str):
        """Send JSON data to specific client"""
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(data)
            except Exception as _exc:  # Broad catch: WebSocket handler resilience
                logger.exception(
                    "websocket_send_json_error error_code=%s client_id=%s",
                    ErrorCode.WS_MESSAGE_SEND_FAILED.value,
                    client_id,
                )
                self.disconnect(client_id)

    async def broadcast(self, message: str):
        """Broadcast message to all connected clients"""
        disconnected = []
        # BE-3008a: snapshot + bounded send so a concurrent (dis)connect can't
        # mutate the live dict mid-iteration and a wedged client can't hang it.
        for client_id, websocket in list(self.active_connections.items()):
            try:
                await asyncio.wait_for(websocket.send_text(message), timeout=_WS_SEND_TIMEOUT_SECONDS)
            except Exception as _exc:  # Broad catch incl. TimeoutError
                logger.exception(
                    "websocket_broadcast_error error_code=%s client_id=%s",
                    ErrorCode.WS_BROADCAST_FAILED.value,
                    client_id,
                )
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            self.disconnect(client_id)

    async def broadcast_json(self, data: dict):
        """Broadcast JSON data to all connected clients"""
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
        """Broadcast an event to all connected clients in a tenant.

        This is the canonical tenant broadcast entrypoint. It always sends a
        standardized event envelope: {type, timestamp, schema_version, data}.
        """
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

    async def notify_entity_update(self, entity_type: str, entity_id: str, update_data: dict):
        """Notify all subscribers of an entity update"""
        entity_key = f"{entity_type}:{entity_id}"

        if entity_key in self.entity_subscribers:
            message = {"type": "entity_update", "entity_type": entity_type, "entity_id": entity_id, "data": update_data}

            # BE-3008a: snapshot the subscriber set — a failed send disconnects the
            # client, mutating this set ("Set changed size during iteration"). Send
            # bounded with ONE deferred cleanup path (not send_json, whose inline
            # disconnect would mutate mid-iteration).
            disconnected = []
            for client_id in list(self.entity_subscribers[entity_key]):
                websocket = self.active_connections.get(client_id)
                if websocket is None:
                    continue
                try:
                    await asyncio.wait_for(websocket.send_json(message), timeout=_WS_SEND_TIMEOUT_SECONDS)
                except Exception as _exc:  # Broad catch incl. TimeoutError: WebSocket handler resilience
                    logger.exception(
                        "websocket_notify_error error_code=%s client_id=%s",
                        ErrorCode.WS_MESSAGE_SEND_FAILED.value,
                        client_id,
                    )
                    disconnected.append(client_id)

            # Clean up disconnected clients (single deferred path).
            for client_id in disconnected:
                self.disconnect(client_id)

    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)

    def get_subscription_count(self, entity_type: str | None = None, entity_id: str | None = None) -> int:
        """Get number of subscriptions for an entity"""
        if entity_type and entity_id:
            entity_key = f"{entity_type}:{entity_id}"
            return len(self.entity_subscribers.get(entity_key, []))
        return sum(len(subs) for subs in self.subscriptions.values())

    # Enhanced broadcast methods for real-time updates
    # Note: broadcast_agent_update method is defined later with full multi-tenant support

    # BE-9012d: broadcast_message_update (the bus REST message-queue WS notifier,
    # api/endpoints/messages.py's only caller) was removed with the bus REST layer.

    async def broadcast_project_update(
        self,
        project_id: str,
        update_type: str,
        project_data: dict,  # 'created', 'status_changed', 'closed', 'updated'
        tenant_key: str | None = None,
    ):
        """Broadcast project updates to all clients in the tenant.

        Uses tenant-scoped delivery so both project detail views and the
        project list page receive real-time updates across all browsers.
        """
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
            },
        )

    # Heartbeat mechanism

    async def start_heartbeat(self, interval: int = 30):
        """Start heartbeat mechanism to keep connections alive"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.send_heartbeat()
            except asyncio.CancelledError:
                # Clean shutdown — let it propagate, do NOT log-and-continue.
                raise
            except Exception:
                # BE-9016 (Sentry GILJOAI-BACKEND-B) defense-in-depth: a bad cycle
                # must not kill the loop. send_heartbeat already drops any client
                # whose send fails, so reaching here means something unexpected
                # (not a per-client disconnect) -- log and keep the task alive; the
                # _start_supervised_heartbeat wrapper in api/startup/core_services.py
                # restarts the task on outright death, but that has an observable
                # gap (missed heartbeats) this loop-body catch avoids entirely.
                logger.exception("Heartbeat cycle failed; continuing")

    async def send_heartbeat(self):
        """Send heartbeat ping to all connected clients"""
        heartbeat = {"type": "ping", "timestamp": datetime.now(UTC).isoformat()}

        disconnected = []
        # BE-3008a: snapshot + bounded send. A bare loop over the live dict across
        # an await let a wedged client stall the whole heartbeat.
        for client_id, websocket in list(self.active_connections.items()):
            try:
                await asyncio.wait_for(websocket.send_json(heartbeat), timeout=_WS_SEND_TIMEOUT_SECONDS)
            except (
                RuntimeError,
                OSError,
                TimeoutError,
                # BE-9016 (Sentry GILJOAI-BACKEND-B): a client that already
                # disconnected raises one of these on send, not the uvicorn
                # ClientDisconnected (OSError) this tuple used to only catch --
                # any send failure means "client gone", so drop it like the rest.
                WebSocketDisconnect,
                websockets.exceptions.ConnectionClosed,
            ) as e:
                logger.debug(f"Heartbeat failed for {client_id}: {e}")
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            self.disconnect(client_id)
            logger.info(f"Removed inactive connection: {client_id}")

    async def broadcast_agent_update(
        self,
        agent_id: str,
        agent_name: str,
        project_id: str,
        tenant_key: str,
        status: str,
        context_usage: int,
        context_delta: int | None = None,
        current_task: str | None = None,
        progress_percentage: int | None = None,
        meta_data: dict | None = None,
        block_reason: str | None = None,  # Handover 0491: Replaced failure_reason
    ):
        """Broadcast real-time status updates during agent execution."""
        data: dict[str, Any] = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "project_id": project_id,
            "tenant_key": tenant_key,
            "status": status,
            "context_usage": context_usage,
            "context_delta": context_delta,
            "current_task": current_task,
            "progress_percentage": progress_percentage,
            "meta_data": meta_data or {},
            "update_time": datetime.now(UTC).isoformat(),
        }

        if status in ("blocked", "silent", "idle", "sleeping") and block_reason:
            data["block_reason"] = block_reason

        event = EventFactory.tenant_envelope(
            event_type="agent:update",
            tenant_key=tenant_key,
            data=data,
            schema_version="1.0",
        )

        await self.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

        await self.notify_entity_update("project", project_id, event)
        await self.notify_entity_update("agent", f"{project_id}:{agent_name}", event)

        logger.debug(f"Broadcast agent:update - {agent_name} (status: {status}, context: {context_usage})")

    # Agent Job Event Broadcasts (Handover 0019, 0286, 0362)

    async def broadcast_job_created(
        self,
        job_id: str,
        agent_display_name: str,
        tenant_key: str,
        spawned_by: str | None = None,
        mission_preview: str | None = None,
        created_at: datetime | None = None,
        project_id: str | None = None,
        agent_name: str | None = None,
        status: str = "waiting",
        execution_id: str | None = None,  # Handover 0457: Unique row ID for frontend Map key
        agent_id: str | None = None,  # Handover 0457: Executor UUID
    ):
        """Broadcast agent job creation events."""
        created_ts = (created_at or datetime.now(UTC)).isoformat()

        job_event = EventFactory.tenant_envelope(
            event_type="agent_job:created",
            tenant_key=tenant_key,
            data={
                "tenant_key": tenant_key,
                "job_id": job_id,
                "agent_display_name": agent_display_name,
                "spawned_by": spawned_by,
                "mission_preview": mission_preview,
                "created_at": created_ts,
                "project_id": project_id,
                "agent_name": agent_name,
                "status": status,
                "execution_id": execution_id,  # Handover 0457
                "agent_id": agent_id,  # Handover 0457
            },
            schema_version="1.0",
        )

        await self.broadcast_event_to_tenant(tenant_key=tenant_key, event=job_event)

        if project_id:
            agent_event = EventFactory.tenant_envelope(
                event_type="agent:created",
                tenant_key=tenant_key,
                data={
                    "tenant_key": tenant_key,
                    "project_id": project_id,
                    "execution_id": execution_id,  # Handover 0457: Unique row ID for frontend Map key
                    "agent_id": agent_id,  # Handover 0457: Executor UUID
                    "job_id": job_id,
                    "agent_display_name": agent_display_name,
                    "agent_name": agent_name,
                    "status": status,
                },
                schema_version="1.0",
            )

            await self.broadcast_event_to_tenant(tenant_key=tenant_key, event=agent_event)

        logger.info(
            f"Broadcast agent_job:created - {job_id} (type: {agent_display_name}, spawned_by: {spawned_by}, project_id: {project_id})"
        )

    async def broadcast_job_status_update(
        self,
        job_id: str,
        agent_display_name: str,
        tenant_key: str,
        old_status: str,
        new_status: str,
        updated_at: datetime | None = None,
        duration_seconds: float | None = None,
        project_id: str | None = None,
    ):
        """Broadcast agent job status change event.

        Handover 0463: Added project_id to enable frontend project-aware filtering
        and prevent cross-project ghost rows.
        """
        event_type = "agent:status_changed"

        message_data: dict[str, Any] = {
            "job_id": job_id,
            "agent_display_name": agent_display_name,
            "old_status": old_status,
            "status": new_status,
            "tenant_key": tenant_key,
            "updated_at": (updated_at or datetime.now(UTC)).isoformat(),
        }

        # Handover 0463: Include project_id for frontend project-aware filtering
        if project_id is not None:
            message_data["project_id"] = project_id

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

    # BE-9012d: broadcast_job_message / broadcast_message_sent /
    # broadcast_message_received / broadcast_message_acknowledged (bus WS emitters)
    # were removed with the bus hard-removal. The Hub (post_to_thread) is
    # deliberately poll-based and has no WebSocket event of its own.

    # Agent Health Monitoring Events (Handover 0106)

    async def broadcast_health_alert(
        self,
        tenant_key: str,
        job_id: str,
        agent_display_name: str,
        health_status: Any,
    ):
        """Broadcast agent health alert."""
        message_data: dict[str, Any] = {
            "tenant_key": tenant_key,
            "job_id": job_id,
            "agent_display_name": agent_display_name,
            "health_state": health_status.health_state,
            "issue_description": health_status.issue_description,
            "minutes_since_update": health_status.minutes_since_update,
            "recommended_action": health_status.recommended_action,
            "execution_id": health_status.execution_id,
            "project_id": health_status.project_id,
            "project_name": health_status.project_name,
        }

        event = EventFactory.tenant_envelope(
            event_type="agent:health_alert",
            tenant_key=tenant_key,
            data=message_data,
            schema_version="1.0",
        )

        await self.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

        logger.warning(
            "broadcast_health_alert job_id=%s health_state=%s minutes_since_update=%s",
            job_id,
            health_status.health_state,
            round(health_status.minutes_since_update, 1),
        )

    async def broadcast_agent_auto_failed(
        self,
        tenant_key: str,
        job_id: str,
        agent_display_name: str,
        reason: str,
    ):
        """Broadcast agent auto-fail event."""
        message_data: dict[str, Any] = {
            "tenant_key": tenant_key,
            "job_id": job_id,
            "agent_display_name": agent_display_name,
            "reason": reason,
            "auto_failed": True,
        }

        event = EventFactory.tenant_envelope(
            event_type="agent:auto_failed",
            tenant_key=tenant_key,
            data=message_data,
            schema_version="1.0",
        )

        await self.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)

        logger.error(
            "broadcast_auto_failed job_id=%s reason=%s",
            job_id,
            reason,
        )
