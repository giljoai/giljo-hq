# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import bcrypt
import pytest

from api.broker.base import WebSocketBrokerMessage, WebSocketEventBroker
from api.websocket import WebSocketManager




class _FakeWS:

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def send_json(self, data: dict) -> None:
        self.sent.append(json.dumps(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class _FakeBroker(WebSocketEventBroker):

    def __init__(self) -> None:
        self.published: list[WebSocketBrokerMessage] = []
        self.handler = None

    def subscribe(self, handler):
        self.handler = handler

        def _unsub() -> None:
            self.handler = None

        return _unsub

    async def publish(self, message: WebSocketBrokerMessage) -> None:
        self.published.append(message)


def _wire(mgr: WebSocketManager, client_id: str, ws: _FakeWS, tenant_key: str) -> None:
    mgr.active_connections[client_id] = ws
    mgr.auth_contexts[client_id] = {"tenant_key": tenant_key}
    mgr._index_tenant_connection(client_id, tenant_key)


def _force_multiworker(monkeypatch) -> None:
    import api.startup.database as db_startup

    monkeypatch.setattr(db_startup, "_worker_count", lambda: 2)




@pytest.mark.asyncio
async def test_disconnect_tenant_closes_only_target_tenant_and_deregisters():
    mgr = WebSocketManager()
    a1, a2, b1 = _FakeWS(), _FakeWS(), _FakeWS()
    _wire(mgr, "a1", a1, "tenant_A")
    _wire(mgr, "a2", a2, "tenant_A")
    _wire(mgr, "b1", b1, "tenant_B")

    closed = await mgr.disconnect_tenant("tenant_A", publish_to_broker=False)

    assert closed == 2
    assert a1.closed and a2.closed
    assert a1.close_code == 1008
    assert a1.close_reason == "account deactivated"
    assert "a1" not in mgr.active_connections
    assert "a2" not in mgr.active_connections
    assert "tenant_A" not in mgr.tenant_connections
    assert not b1.closed
    assert "b1" in mgr.active_connections


@pytest.mark.asyncio
async def test_disconnect_tenant_no_sockets_is_noop():
    mgr = WebSocketManager()
    closed = await mgr.disconnect_tenant("tenant_empty", publish_to_broker=False)
    assert closed == 0


@pytest.mark.asyncio
async def test_disconnect_tenant_rejects_empty_tenant_key():
    mgr = WebSocketManager()
    with pytest.raises(ValueError):
        await mgr.disconnect_tenant("", publish_to_broker=False)


@pytest.mark.asyncio
async def test_disconnect_tenant_publishes_control_when_multiworker(monkeypatch):
    _force_multiworker(monkeypatch)
    mgr = WebSocketManager()
    broker = _FakeBroker()
    mgr.attach_broker(broker)

    a1 = _FakeWS()
    _wire(mgr, "a1", a1, "tenant_A")

    await mgr.disconnect_tenant("tenant_A")

    assert a1.closed
    assert len(broker.published) == 1
    msg = broker.published[0]
    assert msg.control == "disconnect_tenant"
    assert msg.tenant_key == "tenant_A"
    assert msg.origin == mgr._broker_origin


@pytest.mark.asyncio
async def test_disconnect_tenant_single_worker_does_not_publish(monkeypatch):
    import api.startup.database as db_startup

    monkeypatch.setattr(db_startup, "_worker_count", lambda: 1)
    mgr = WebSocketManager()
    broker = _FakeBroker()
    mgr.attach_broker(broker)
    _wire(mgr, "a1", _FakeWS(), "tenant_A")

    await mgr.disconnect_tenant("tenant_A")

    assert broker.published == []


@pytest.mark.asyncio
async def test_peer_control_message_closes_local_sockets_without_republishing(monkeypatch):
    _force_multiworker(monkeypatch)
    mgr = WebSocketManager()
    broker = _FakeBroker()
    mgr.attach_broker(broker)
    a1 = _FakeWS()
    _wire(mgr, "a1", a1, "tenant_A")

    peer_msg = WebSocketBrokerMessage(
        tenant_key="tenant_A",
        event={},
        origin="some-other-worker-origin",
        control="disconnect_tenant",
    )
    await broker.handler(peer_msg)

    assert a1.closed
    assert "a1" not in mgr.active_connections
    assert broker.published == []


@pytest.mark.asyncio
async def test_own_echo_control_message_is_ignored(monkeypatch):
    _force_multiworker(monkeypatch)
    mgr = WebSocketManager()
    broker = _FakeBroker()
    mgr.attach_broker(broker)
    a1 = _FakeWS()
    _wire(mgr, "a1", a1, "tenant_A")

    own_msg = WebSocketBrokerMessage(
        tenant_key="tenant_A",
        event={},
        origin=mgr._broker_origin,
        control="disconnect_tenant",
    )
    await broker.handler(own_msg)

    assert not a1.closed
    assert "a1" in mgr.active_connections


def test_broker_message_control_survives_serialization_roundtrip():
    from api.broker.postgres_notify import PostgresNotifyWebSocketEventBroker as B

    msg = WebSocketBrokerMessage(tenant_key="tenant_A", event={}, origin="orig", control="disconnect_tenant")
    restored = B._deserialize(B._serialize(msg))
    assert restored.control == "disconnect_tenant"
    assert restored.tenant_key == "tenant_A"
    assert restored.origin == "orig"




class _RecordingWsManager:

    def __init__(self) -> None:
        self.disconnects: list[str] = []

    async def disconnect_tenant(self, tenant_key: str, *, reason: str = "", **_) -> int:
        self.disconnects.append(tenant_key)
        return 0


async def _seed_user(db_manager) -> tuple[str, str]:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tk = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tk) as session:
        org = Organization(
            name=f"TSK9006 Org {unique}",
            slug=f"tsk9006-org-{unique}",
            tenant_key=tk,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=f"tsk9006_user_{unique}",
                email=f"tsk9006_{unique}@example.com",
                password_hash=bcrypt.hashpw(b"Password1!", bcrypt.gensalt()).decode("utf-8"),
                tenant_key=tk,
                role="developer",
                org_id=org.id,
                is_active=True,
                token_revocation_epoch=0,
            )
        )
        await session.commit()

    return user_id, tk


async def _read_user(db_manager, *, tenant_key: str, user_id: str):
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        user = await session.get(User, user_id)
        return int(user.token_revocation_epoch or 0), bool(user.is_active)


@pytest.fixture
def spy_ws_manager(monkeypatch):
    from api import app_state

    spy = _RecordingWsManager()
    monkeypatch.setattr(app_state.state, "websocket_manager", spy, raising=False)
    return spy


def _service(db_manager, tenant_key: str):
    from giljo_mcp.services.user_service import UserService

    return UserService(db_manager=db_manager, tenant_key=tenant_key)


@pytest.mark.asyncio
async def test_update_deactivate_bumps_epoch_and_closes_sockets(db_manager, spy_ws_manager):
    user_id, tk = await _seed_user(db_manager)

    await _service(db_manager, tk).update_user(user_id, is_active=False)

    epoch, is_active = await _read_user(db_manager, tenant_key=tk, user_id=user_id)
    assert epoch == 1
    assert is_active is False
    assert spy_ws_manager.disconnects == [tk]


@pytest.mark.asyncio
async def test_reactivation_does_not_resurrect_or_close(db_manager, spy_ws_manager):
    user_id, tk = await _seed_user(db_manager)
    svc = _service(db_manager, tk)

    await svc.update_user(user_id, is_active=False)
    assert spy_ws_manager.disconnects == [tk]

    await svc.update_user(user_id, is_active=True)

    epoch, is_active = await _read_user(db_manager, tenant_key=tk, user_id=user_id)
    assert epoch == 1
    assert is_active is True
    assert spy_ws_manager.disconnects == [tk]


@pytest.mark.asyncio
async def test_non_active_update_evicts_nothing(db_manager, spy_ws_manager):
    user_id, tk = await _seed_user(db_manager)

    await _service(db_manager, tk).update_user(user_id, first_name="Renamed")

    epoch, _ = await _read_user(db_manager, tenant_key=tk, user_id=user_id)
    assert epoch == 0
    assert spy_ws_manager.disconnects == []


@pytest.mark.asyncio
async def test_delete_user_soft_delete_evicts_and_closes_sockets(db_manager, spy_ws_manager):
    user_id, tk = await _seed_user(db_manager)

    await _service(db_manager, tk).delete_user(user_id)

    epoch, is_active = await _read_user(db_manager, tenant_key=tk, user_id=user_id)
    assert epoch == 1
    assert is_active is False
    assert spy_ws_manager.disconnects == [tk]
