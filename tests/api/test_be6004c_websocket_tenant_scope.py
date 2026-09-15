# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import contextlib
import secrets
import uuid

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import PostgreSQLTestHelper


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _build_portal_db_manager():
    from giljo_mcp.database import DatabaseManager

    await PostgreSQLTestHelper.ensure_test_database_exists()
    db_manager = DatabaseManager(PostgreSQLTestHelper.get_test_db_url(), is_async=True, use_null_pool=True)
    return db_manager


async def _seed_tenant_with_project(db_manager) -> dict:
    suffix = uuid.uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(
            name=f"WS Org {suffix}",
            slug=f"ws-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"ws_user_{suffix}",
            email=f"ws_user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name=f"WS Project {suffix}",
            description="Subscribe target for the WS tenant-scope regression test",
            mission="WS regression",
            status="active",
            tenant_key=tenant_key,
            product_id=_owning_product_project.id,
            series_number=int(uuid.uuid4().int % 900000) + 100000,
        )
        session.add(project)
        await session.commit()

    token = JWTManager.create_access_token(
        user_id=user.id,
        username=user.username,
        role="developer",
        tenant_key=tenant_key,
    )
    return {"tenant_key": tenant_key, "token": token, "project_id": project.id}


async def _cleanup_tenant(db_manager, tenant_key: str) -> None:
    from giljo_mcp.database import tenant_session_context

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
            await session.execute(delete(User).where(User.tenant_key == tenant_key))
            await session.execute(delete(Organization).where(Organization.tenant_key == tenant_key))
            await session.commit()


@contextlib.contextmanager
def _no_op_lifespan(app):
    original = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _noop(_app):
        yield

    app.router.lifespan_context = _noop
    try:
        yield
    finally:
        app.router.lifespan_context = original


def _install_ws_app_state(db_manager):
    from unittest.mock import MagicMock

    from api.app import app
    from api.app_state import state
    from api.websocket import WebSocketManager
    from giljo_mcp.auth import AuthManager
    from giljo_mcp.tenant import TenantManager as _TenantManager

    prev = {
        "db_manager": state.db_manager,
        "websocket_manager": state.websocket_manager,
        "tenant_manager": state.tenant_manager,
        "config": state.config,
        "auth": state.auth,
        "app_db_manager": getattr(app.state, "db_manager", None),
        "app_ws_manager": getattr(app.state, "websocket_manager", None),
    }

    state.db_manager = db_manager
    app.state.db_manager = db_manager
    state.websocket_manager = WebSocketManager()
    app.state.websocket_manager = state.websocket_manager
    if state.tenant_manager is None:
        state.tenant_manager = _TenantManager()

    mock_config = MagicMock()
    mock_config.jwt.secret_key = "test_secret_key"
    mock_config.jwt.algorithm = "HS256"
    mock_config.jwt.expiration_minutes = 30
    mock_config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "security.auth_enabled": True,
            "security.api_keys_required": False,
        }.get(key, default)
    )
    state.config = mock_config
    app.state.config = mock_config
    app.state.auth = AuthManager(mock_config, db=None)
    state.auth = app.state.auth

    def restore():
        state.db_manager = prev["db_manager"]
        state.websocket_manager = prev["websocket_manager"]
        state.tenant_manager = prev["tenant_manager"]
        state.config = prev["config"]
        state.auth = prev["auth"]
        app.state.db_manager = prev["app_db_manager"]
        app.state.websocket_manager = prev["app_ws_manager"]

    return restore


@pytest.mark.tenant_isolation
def test_authenticated_ws_handshake_succeeds_and_subscribe_delivers_event(monkeypatch):
    from api.app import app

    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    with _no_op_lifespan(app), TestClient(app) as client:
        db_manager = client.portal.call(_build_portal_db_manager)
        restore = _install_ws_app_state(db_manager)
        seeded = client.portal.call(_seed_tenant_with_project, db_manager)
        client_id = f"ws-test-{uuid.uuid4().hex[:8]}"
        try:
            with client.websocket_connect(f"/ws/{client_id}?token={seeded['token']}") as ws:
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong == {"type": "pong"}, pong

                ws.send_json({"type": "subscribe", "entity_type": "project", "entity_id": seeded["project_id"]})
                msg = ws.receive_json()
                assert msg.get("type") == "subscribed", msg
                assert msg.get("entity_type") == "project", msg
                assert msg.get("entity_id") == seeded["project_id"], msg
        finally:
            client.portal.call(_cleanup_tenant, db_manager, seeded["tenant_key"])
            client.portal.call(db_manager.close_async)
            restore()


@pytest.mark.tenant_isolation
def test_ws_subscribe_blocks_cross_tenant_project(monkeypatch):
    from api.app import app

    monkeypatch.setenv("GILJO_TENANT_GUARD_MODE", "enforce")

    with _no_op_lifespan(app), TestClient(app) as client:
        db_manager = client.portal.call(_build_portal_db_manager)
        restore = _install_ws_app_state(db_manager)
        caller = client.portal.call(_seed_tenant_with_project, db_manager)
        other = client.portal.call(_seed_tenant_with_project, db_manager)
        client_id = f"ws-xtenant-{uuid.uuid4().hex[:8]}"
        try:
            with client.websocket_connect(f"/ws/{client_id}?token={caller['token']}") as ws:
                ws.send_json({"type": "subscribe", "entity_type": "project", "entity_id": other["project_id"]})
                msg = ws.receive_json()
                assert msg.get("type") == "error", msg
                assert msg.get("error") == "subscription_denied", msg
        finally:
            client.portal.call(_cleanup_tenant, db_manager, caller["tenant_key"])
            client.portal.call(_cleanup_tenant, db_manager, other["tenant_key"])
            client.portal.call(db_manager.close_async)
            restore()
