# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

import asyncpg

from api.broker.base import BrokerHandler, WebSocketBrokerMessage, WebSocketEventBroker
from giljo_mcp.logging import ErrorCode


logger = logging.getLogger(__name__)

_RECONNECT_INITIAL_DELAY_SECONDS = 0.5
_RECONNECT_MAX_DELAY_SECONDS = 30.0
_MAX_NOTIFY_PAYLOAD_BYTES = 7999

_PUBLISH_POOL_MIN_SIZE = 1
_PUBLISH_POOL_MAX_SIZE = 5
MAX_DB_CONNECTIONS_PER_PROCESS = 1 + _PUBLISH_POOL_MAX_SIZE


class PostgresNotifyWebSocketEventBroker(WebSocketEventBroker):

    def __init__(self, *, dsn: str, channel: str = "giljo_ws_events") -> None:
        self._dsn = dsn
        self._channel = channel
        self._handlers: set[BrokerHandler] = set()
        self._listen_conn: asyncpg.Connection | None = None
        self._publish_pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()
        self._reconnect_task: asyncio.Task | None = None
        self._connection_lost = asyncio.Event()
        self._stopping = False

    async def start(self) -> None:
        if self._listen_conn or self._publish_pool:
            return

        self._stopping = False
        self._connection_lost.clear()
        try:
            await self._connect_listener()
            self._publish_pool = await asyncpg.create_pool(
                self._dsn, min_size=_PUBLISH_POOL_MIN_SIZE, max_size=_PUBLISH_POOL_MAX_SIZE
            )
        except BaseException:
            await self.stop()
            raise
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        self._stopping = True

        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        if self._listen_conn:
            try:
                self._listen_conn.remove_termination_listener(self._on_listen_connection_lost)
            except (asyncpg.PostgresError, RuntimeError) as e:
                logger.debug(f"Failed removing termination listener: {e}")
            try:
                await self._listen_conn.remove_listener(self._channel, self._on_notification)
            except (asyncpg.PostgresError, RuntimeError) as e:
                logger.debug(f"Failed removing postgres listener: {e}")
            try:
                await self._listen_conn.close()
            except (asyncpg.PostgresError, RuntimeError) as e:
                logger.debug(f"Failed closing postgres listen connection: {e}")
            self._listen_conn = None

        if self._publish_pool:
            try:
                await self._publish_pool.close()
            except (asyncpg.PostgresError, RuntimeError) as e:
                logger.debug(f"Failed closing postgres pool: {e}")
            self._publish_pool = None

    async def _connect_listener(self) -> None:
        conn = await asyncpg.connect(self._dsn)
        await conn.add_listener(self._channel, self._on_notification)
        conn.add_termination_listener(self._on_listen_connection_lost)
        self._listen_conn = conn

    def _on_listen_connection_lost(self, _connection: asyncpg.Connection) -> None:
        self._connection_lost.set()

    async def _reconnect_loop(self) -> None:
        while not self._stopping:
            await self._connection_lost.wait()
            self._connection_lost.clear()
            if self._stopping:
                return

            logger.error(
                "websocket_broker_listen_connection_lost error_code=%s channel=%s; reconnecting",
                ErrorCode.WS_CONNECTION_FAILED.value,
                self._channel,
            )
            old_conn, self._listen_conn = self._listen_conn, None
            if old_conn is not None:
                try:
                    old_conn.remove_termination_listener(self._on_listen_connection_lost)
                except (asyncpg.PostgresError, RuntimeError) as e:
                    logger.debug(f"Failed removing termination listener: {e}")
                if not old_conn.is_closed():
                    try:
                        await old_conn.close()
                    except (asyncpg.PostgresError, RuntimeError, OSError) as e:
                        logger.debug(f"Failed closing lost listen connection: {e}")

            delay = _RECONNECT_INITIAL_DELAY_SECONDS
            while not self._stopping:
                try:
                    await self._connect_listener()
                    logger.warning(
                        "websocket_broker_listen_reconnected channel=%s",
                        self._channel,
                    )
                    break
                except Exception:
                    logger.exception(
                        "websocket_broker_listen_reconnect_failed error_code=%s retry_in_seconds=%.1f",
                        ErrorCode.WS_CONNECTION_FAILED.value,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, _RECONNECT_MAX_DELAY_SECONDS)

    def subscribe(self, handler: BrokerHandler) -> Callable[[], None]:
        self._handlers.add(handler)

        def _unsubscribe() -> None:
            self._handlers.discard(handler)

        return _unsubscribe

    async def publish(self, message: WebSocketBrokerMessage) -> None:
        if not self._publish_pool:
            raise RuntimeError("PostgresNotifyWebSocketEventBroker is not started")

        payload = self._serialize(message)
        payload_size = len(payload.encode("utf-8"))
        if payload_size > _MAX_NOTIFY_PAYLOAD_BYTES:
            raise ValueError(
                f"NOTIFY payload is {payload_size} bytes; pg_notify caps payloads at "
                f"{_MAX_NOTIFY_PAYLOAD_BYTES} bytes. Trim the event (send ids, not blobs)."
            )
        async with self._publish_pool.acquire() as conn:
            await conn.execute("SELECT pg_notify($1, $2)", self._channel, payload)

    @staticmethod
    def _serialize(message: WebSocketBrokerMessage) -> str:
        return json.dumps(
            {
                "tenant_key": message.tenant_key,
                "event": message.event,
                "exclude_client": message.exclude_client,
                "origin": message.origin,
                "control": message.control,
            }
        )

    @staticmethod
    def _deserialize(payload: str) -> WebSocketBrokerMessage:
        decoded = json.loads(payload)
        return WebSocketBrokerMessage(
            tenant_key=decoded["tenant_key"],
            event=decoded["event"],
            exclude_client=decoded.get("exclude_client"),
            origin=decoded.get("origin"),
            control=decoded.get("control"),
        )

    def _on_notification(self, _connection: asyncpg.Connection, _pid: int, _channel: str, payload: str) -> None:
        task = asyncio.create_task(self._handle_payload(payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _handle_payload(self, payload: str) -> None:
        try:
            message = self._deserialize(payload)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to deserialize broker payload: {e}", exc_info=True)
            return

        async with self._lock:
            handlers_snapshot = list(self._handlers)

        for handler in handlers_snapshot:
            try:
                await handler(message)
            except Exception as e:  # noqa: BLE001 - Handler resilience: continue loop on any error
                logger.warning(f"Broker handler failed: {e}", exc_info=True)
