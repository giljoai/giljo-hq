# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.oauth import OAuthLogin, OAuthLoginIp
from giljo_mcp.services import oauth_login_service
from tests.api.test_mcp_session import _drive_middleware_with_body
from tests.api.test_oauth_refresh import (
    _bcrypt_hash,
    _generate_pkce_pair,
    _install_confidential_resolver,
    _seed_user_and_code,
)


pytestmark = pytest.mark.asyncio

CANONICAL_MCP_URI = "http://test/mcp"
CLIENT_NAME = "DCR Confidential Test Client"
_REDIRECT = "http://localhost:3000/callback"
_CALL = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()


class _Inner:
    async def __call__(self, scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


async def _connect_app(api_client, db_manager) -> dict:
    verifier, challenge = _generate_pkce_pair()
    code_value = secrets.token_urlsafe(64)
    client_id = str(uuid4())
    secret = secrets.token_urlsafe(48)
    tenant_key = await _seed_user_and_code(db_manager, challenge=challenge, code_value=code_value, client_id=client_id)
    restore = _install_confidential_resolver((client_id, _bcrypt_hash(secret), [_REDIRECT]))
    try:
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code_value,
                "client_id": client_id,
                "code_verifier": verifier,
                "redirect_uri": _REDIRECT,
                "client_secret": secret,
                "resource": CANONICAL_MCP_URI,
            },
        )
    finally:
        restore()
    assert response.status_code == 200, response.text
    body = response.json()
    claims = json.loads(base64.urlsafe_b64decode(body["access_token"].split(".")[1] + "=="))
    return {"tokens": body, "tenant_key": tenant_key, "client_id": client_id, "claims": claims, "secret": secret}


async def _mcp_call(db_manager, access_token: str, *, extra_headers=()) -> int:
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    prior = state.db_manager
    state.db_manager = db_manager
    try:
        status, _headers, _body = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=_Inner()),
            headers=[
                (b"authorization", f"Bearer {access_token}".encode()),
                (b"content-type", b"application/json"),
                (b"user-agent", b"TestAgent/1.0"),
                *extra_headers,
            ],
            body=_CALL,
        )
        return status
    finally:
        state.db_manager = prior


async def _logins(db_manager, tenant_key: str) -> list[OAuthLogin]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            rows = await session.execute(select(OAuthLogin).where(OAuthLogin.tenant_key == tenant_key))
            return list(rows.scalars().all())


async def _ips(db_manager, tenant_key: str, login_id: str) -> list[OAuthLoginIp]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            rows = await session.execute(
                select(OAuthLoginIp).where(OAuthLoginIp.tenant_key == tenant_key, OAuthLoginIp.login_id == login_id)
            )
            return list(rows.scalars().all())


async def test_an_oauth_call_leaves_a_record_of_app_and_address(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    assert app["claims"].get("fid"), "the access token must carry its refresh family"

    assert await _mcp_call(db_manager, app["tokens"]["access_token"]) == 200

    (login,) = await _logins(db_manager, app["tenant_key"])
    assert login.client_name == CLIENT_NAME
    assert login.client_id == app["client_id"]
    assert login.last_ip == "127.0.0.1"
    assert login.last_user_agent == "TestAgent/1.0"
    assert login.last_used_at is not None
    assert str(login.family_id) == app["claims"]["fid"]
    assert [row.ip_address for row in await _ips(db_manager, app["tenant_key"], login.id)] == ["127.0.0.1"]


async def test_the_refresh_grant_keeps_the_family_and_recreates_a_missing_login(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    tenant_key = app["tenant_key"]
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(OAuthLogin.__table__.delete().where(OAuthLogin.tenant_key == tenant_key))
    assert await _logins(db_manager, tenant_key) == []

    restore = _install_confidential_resolver((app["client_id"], _bcrypt_hash(app["secret"]), [_REDIRECT]))
    try:
        response = await api_client.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": app["tokens"]["refresh_token"],
                "client_id": app["client_id"],
                "client_secret": app["secret"],
            },
        )
    finally:
        restore()
    assert response.status_code == 200, response.text
    new_claims = json.loads(base64.urlsafe_b64decode(response.json()["access_token"].split(".")[1] + "=="))
    assert new_claims["fid"] == app["claims"]["fid"]
    (login,) = await _logins(db_manager, tenant_key)
    assert str(login.family_id) == app["claims"]["fid"]
    assert login.client_name == CLIENT_NAME


async def test_a_logged_out_app_is_refused_on_its_next_call(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    token = app["tokens"]["access_token"]
    assert await _mcp_call(db_manager, token) == 200
    (login,) = await _logins(db_manager, app["tenant_key"])
    user_id = login.user_id

    async with db_manager.get_session_async(tenant_key=app["tenant_key"]) as session:
        with tenant_session_context(session, app["tenant_key"]):
            await oauth_login_service.log_out_app(
                session, tenant_key=app["tenant_key"], user_id=user_id, login_id=login.id
            )

    assert await _mcp_call(db_manager, token) == 401


async def test_log_out_all_refuses_every_app_of_the_user(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    token = app["tokens"]["access_token"]
    (login,) = await _logins(db_manager, app["tenant_key"])

    async with db_manager.get_session_async(tenant_key=app["tenant_key"]) as session:
        with tenant_session_context(session, app["tenant_key"]):
            await oauth_login_service.log_out_all_apps(session, tenant_key=app["tenant_key"], user_id=login.user_id)
            assert (
                await oauth_login_service.list_connected_apps(
                    session, tenant_key=app["tenant_key"], user_id=login.user_id
                )
                == []
            )

    assert await _mcp_call(db_manager, token) == 401


async def test_a_spoofed_cf_connecting_ip_is_ignored_without_a_trusted_proxy(api_client, db_manager, monkeypatch):
    from api.endpoints.auth.session import _get_ip_resolver

    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.delenv("GILJO_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    _get_ip_resolver.cache_clear()
    try:
        app = await _connect_app(api_client, db_manager)
        await _mcp_call(
            db_manager,
            app["tokens"]["access_token"],
            extra_headers=[(b"cf-connecting-ip", b"203.0.113.9"), (b"x-forwarded-for", b"203.0.113.9")],
        )
    finally:
        _get_ip_resolver.cache_clear()
    (login,) = await _logins(db_manager, app["tenant_key"])
    assert login.last_ip == "127.0.0.1"


async def test_cf_connecting_ip_is_honoured_from_a_trusted_proxy(api_client, db_manager, monkeypatch):
    from api.endpoints.auth.session import _get_ip_resolver

    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    monkeypatch.setenv("GILJO_TRUSTED_PROXIES", "127.0.0.1")
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    _get_ip_resolver.cache_clear()
    try:
        app = await _connect_app(api_client, db_manager)
        await _mcp_call(
            db_manager,
            app["tokens"]["access_token"],
            extra_headers=[(b"cf-connecting-ip", b"203.0.113.9")],
        )
    finally:
        _get_ip_resolver.cache_clear()
    (login,) = await _logins(db_manager, app["tenant_key"])
    assert login.last_ip == "203.0.113.9"


async def test_a_second_call_inside_the_minute_from_the_same_address_writes_nothing(
    api_client, db_manager, monkeypatch
):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    for _ in range(3):
        await _mcp_call(db_manager, app["tokens"]["access_token"])
    (login,) = await _logins(db_manager, app["tenant_key"])
    (ip_row,) = await _ips(db_manager, app["tenant_key"], login.id)
    assert ip_row.request_count == 1


async def test_only_the_newest_ten_addresses_are_kept(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    tenant_key = app["tenant_key"]
    (login,) = await _logins(db_manager, tenant_key)
    for n in range(13):
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            with tenant_session_context(session, tenant_key):
                await oauth_login_service.record_use(
                    session,
                    tenant_key=tenant_key,
                    family_id=str(login.family_id),
                    ip=f"198.51.100.{n}",
                    user_agent=None,
                    mcp_client_name=None,
                )
    kept = {row.ip_address for row in await _ips(db_manager, tenant_key, login.id)}
    assert len(kept) == oauth_login_service.MAX_IPS_PER_LOGIN
    assert "198.51.100.12" in kept
    assert "198.51.100.0" not in kept


async def test_addresses_older_than_ninety_days_are_dropped_on_the_next_write(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    tenant_key = app["tenant_key"]
    (login,) = await _logins(db_manager, tenant_key)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            session.add(
                OAuthLoginIp(
                    login_id=login.id,
                    tenant_key=tenant_key,
                    ip_address="192.0.2.77",
                    last_seen=datetime.now(UTC) - timedelta(days=91),
                )
            )
            await session.flush()
            await oauth_login_service.record_use(
                session,
                tenant_key=tenant_key,
                family_id=str(login.family_id),
                ip="198.51.100.1",
                user_agent=None,
                mcp_client_name=None,
            )
    kept = {row.ip_address for row in await _ips(db_manager, tenant_key, login.id)}
    assert kept == {"198.51.100.1"}


async def test_one_user_never_sees_or_ends_another_users_login(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    alice = await _connect_app(api_client, db_manager)
    bob = await _connect_app(api_client, db_manager)
    (alice_login,) = await _logins(db_manager, alice["tenant_key"])
    (bob_login,) = await _logins(db_manager, bob["tenant_key"])

    async with db_manager.get_session_async(tenant_key=bob["tenant_key"]) as session:
        with tenant_session_context(session, bob["tenant_key"]):
            listed = await oauth_login_service.list_connected_apps(
                session, tenant_key=bob["tenant_key"], user_id=bob_login.user_id
            )
            assert [a.id for a in listed] == [bob_login.id]

            from giljo_mcp.exceptions import ResourceNotFoundError

            with pytest.raises(ResourceNotFoundError):
                await oauth_login_service.log_out_app(
                    session, tenant_key=bob["tenant_key"], user_id=bob_login.user_id, login_id=alice_login.id
                )
            with pytest.raises(ResourceNotFoundError):
                await oauth_login_service.log_out_app(
                    session, tenant_key=alice["tenant_key"], user_id=bob_login.user_id, login_id=alice_login.id
                )

    assert await _mcp_call(db_manager, alice["tokens"]["access_token"]) == 200


async def test_deleting_the_user_removes_the_logins_and_addresses(api_client, db_manager, monkeypatch):
    from giljo_mcp.models.auth import User

    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    tenant_key = app["tenant_key"]
    await _mcp_call(db_manager, app["tokens"]["access_token"])
    (login,) = await _logins(db_manager, tenant_key)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            user = (await session.execute(select(User).where(User.id == login.user_id))).scalar_one()
            await session.delete(user)
    assert await _logins(db_manager, tenant_key) == []
    assert await _ips(db_manager, tenant_key, login.id) == []


async def test_a_password_change_revokes_every_family(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    (login,) = await _logins(db_manager, app["tenant_key"])
    from giljo_mcp.services import oauth_refresh_service

    async with db_manager.get_session_async(tenant_key=app["tenant_key"]) as session:
        with tenant_session_context(session, app["tenant_key"]):
            await oauth_refresh_service.revoke_all_for_user(
                session, user_id=login.user_id, tenant_key=app["tenant_key"]
            )
    assert await _mcp_call(db_manager, app["tokens"]["access_token"]) == 401


async def test_logins_idle_past_retention_are_deleted_when_the_user_connects_again(api_client, db_manager, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    app = await _connect_app(api_client, db_manager)
    tenant_key = app["tenant_key"]
    (login,) = await _logins(db_manager, tenant_key)
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(
                update(OAuthLogin)
                .where(OAuthLogin.id == login.id)
                .values(connected_at=datetime.now(UTC) - timedelta(days=100))
            )
            await oauth_login_service.ensure_login(
                session,
                family_id=str(uuid4()),
                tenant_key=tenant_key,
                user_id=login.user_id,
                client_id="c",
                client_name="Fresh",
            )
            names = (
                (await session.execute(select(OAuthLogin.client_name).where(OAuthLogin.tenant_key == tenant_key)))
                .scalars()
                .all()
            )
            assert list(names) == ["Fresh"]


async def _login_for(api_client, db_manager, headers: dict, name: str) -> tuple[str, str, str]:
    from giljo_mcp.services import oauth_refresh_service

    me = (await api_client.get("/api/auth/me", headers=headers)).json()
    user_id, tenant_key = me["id"], me["tenant_key"]
    family_id = oauth_refresh_service.new_family_id()
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        with tenant_session_context(session, tenant_key):
            await oauth_refresh_service.issue_refresh_token(
                session,
                family_id=family_id,
                client_id="c1",
                tenant_key=tenant_key,
                user_id=user_id,
                scope=None,
                aud="http://test/mcp",
                lifetime_seconds=3600,
            )
            await oauth_login_service.ensure_login(
                session, family_id=family_id, tenant_key=tenant_key, user_id=user_id, client_id="c1", client_name=name
            )
    login = next(row for row in await _logins(db_manager, tenant_key) if row.client_name == name)
    return login.id, user_id, tenant_key


async def test_rest_lists_only_my_live_apps_and_logs_one_out(api_client, db_manager, auth_headers):
    mine, _, _ = await _login_for(api_client, db_manager, auth_headers, "Claude Desktop")
    listed = await api_client.get("/api/auth/connected-apps", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [row["client_name"] for row in listed.json()] == ["Claude Desktop"]
    assert listed.json()[0]["client_id"] == "c1"
    assert "token" not in json.dumps(listed.json()).lower()

    gone = await api_client.delete(f"/api/auth/connected-apps/{mine}", headers=auth_headers)
    assert gone.status_code == 204, gone.text
    assert (await api_client.get("/api/auth/connected-apps", headers=auth_headers)).json() == []


async def test_rest_will_not_log_out_someone_elses_app(api_client, db_manager, auth_headers):
    other_login, _, _ = await _login_for(api_client, db_manager, auth_headers, "Not Yours")
    from uuid import uuid4

    from giljo_mcp.auth.jwt_manager import JWTManager
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager
    from tests.api.conftest import _TEST_CSRF_TOKEN

    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        org = Organization(name="Other", slug=f"other-{uuid4().hex[:8]}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        user = User(
            username=f"other_{uuid4().hex[:8]}",
            email=f"o_{uuid4().hex[:8]}@example.com",
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.commit()
        token = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
    intruder = {
        "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
        "X-CSRF-Token": _TEST_CSRF_TOKEN,
    }

    assert (await api_client.get("/api/auth/connected-apps", headers=intruder)).json() == []
    assert (await api_client.delete(f"/api/auth/connected-apps/{other_login}", headers=intruder)).status_code == 404
    assert len((await api_client.get("/api/auth/connected-apps", headers=auth_headers)).json()) == 1


async def test_rest_log_out_all(api_client, db_manager, auth_headers):
    await _login_for(api_client, db_manager, auth_headers, "App A")
    await _login_for(api_client, db_manager, auth_headers, "App B")
    assert len((await api_client.get("/api/auth/connected-apps", headers=auth_headers)).json()) == 2
    assert (await api_client.delete("/api/auth/connected-apps", headers=auth_headers)).status_code == 200
    assert (await api_client.get("/api/auth/connected-apps", headers=auth_headers)).json() == []


async def test_rest_refuses_a_bearer_token(api_client, db_manager, auth_headers):
    cookie = auth_headers["Cookie"].split(";")[0].split("=", 1)[1]
    response = await api_client.get("/api/auth/connected-apps", headers={"Authorization": f"Bearer {cookie}"})
    assert response.status_code == 403
