# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import secrets
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException, WebSocketException

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.services.oauth_refresh_service import issue_refresh_token, new_family_id
from giljo_mcp.services.oauth_revocation_service import clear_revocation_cache
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID
from tests.security.test_sec3004c_transport_parity import _drive_mcp, _FakeWebSocket


MCP_AUD = "http://test/mcp"
OLD_PASSWORD = "OldPassword1!"
NEW_PASSWORD = "NewPassword2@"
_PASSWORD_CHANGE = {"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD}
_CSRF = secrets.token_urlsafe(32)
_EXPORT_REACHED = 418


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    clear_revocation_cache()
    yield
    clear_revocation_cache()


async def _seed_user(db_manager) -> dict:
    from giljo_mcp.models.auth import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    unique = uuid4().hex[:8]
    user_id = str(uuid4())
    username = f"sec0046_{unique}"
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(name=f"SEC0046 {unique}", slug=f"sec0046-{unique}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                id=user_id,
                username=username,
                email=f"{username}@example.com",
                password_hash=bcrypt.hashpw(OLD_PASSWORD.encode(), bcrypt.gensalt()).decode(),
                tenant_key=tenant_key,
                role="admin",
                org_id=org.id,
                is_active=True,
            )
        )
        await session.commit()
    return {"id": user_id, "username": username, "tenant_key": tenant_key, "role": "admin"}


async def _agent_token(db_manager, user: dict, *, audience: str | None = MCP_AUD, scope: str = "mcp:read") -> str:
    family_id = new_family_id()
    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        await issue_refresh_token(
            session,
            family_id=family_id,
            client_id=BUILTIN_CLIENT_ID,
            tenant_key=user["tenant_key"],
            user_id=user["id"],
            scope=scope,
            aud=audience or "",
            lifetime_seconds=3600,
        )
        await session.commit()
    return JWTManager.create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        tenant_key=user["tenant_key"],
        audience=audience,
        scope=scope,
        revocation_epoch=0,
        family_id=family_id,
    )


def _browser_token(user: dict) -> str:
    return JWTManager.create_access_token(
        user_id=user["id"], username=user["username"], role=user["role"], tenant_key=user["tenant_key"]
    )


def _as_bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Cookie": f"csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


def _as_cookie(token: str) -> dict:
    return {"Cookie": f"access_token={token}; csrf_token={_CSRF}", "X-CSRF-Token": _CSRF}


def _consent_body(scope: str = "mcp:read mcp:write mcp:agent") -> dict:
    return {
        "client_id": BUILTIN_CLIENT_ID,
        "redirect_uri": "http://localhost:3000/callback",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
        "scope": scope,
        "state": "sec0046",
        "response_type": "code",
    }


async def _password_hash(db_manager, user: dict) -> str:
    from giljo_mcp.models.auth import User

    async with db_manager.get_session_async(tenant_key=user["tenant_key"]) as session:
        return (await session.get(User, user["id"])).password_hash


def _assert_generic_401(resp) -> None:
    assert resp.status_code == 401, resp.text
    lowered = resp.text.lower()
    for leak in ("aud", "fid", "scope", "resource"):
        assert leak not in lowered, f"401 body names {leak!r}: {resp.text}"


@pytest.fixture
def export_probe(monkeypatch):
    from api.endpoints import tenant_data

    reached: list[str] = []

    class _Probe:
        def __init__(self, **_kwargs):
            pass

        async def export(self, tenant_key):
            reached.append(tenant_key)
            raise HTTPException(status_code=_EXPORT_REACHED, detail="export reached")

    monkeypatch.setattr(tenant_data, "TenantExportService", _Probe)
    return reached




@pytest.mark.asyncio
async def test_red1_agent_bearer_cannot_self_issue_a_wider_consent_code(api_client, db_manager):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user, scope="mcp:read")

    resp = await api_client.post(
        "/api/oauth/authorize", json=_consent_body(), headers=_as_bearer(token), follow_redirects=False
    )

    _assert_generic_401(resp)
    assert "code=" not in resp.text


@pytest.mark.asyncio
async def test_red2_agent_cookie_cannot_set_a_new_password(api_client, db_manager):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user)
    before = await _password_hash(db_manager, user)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}/password", json=_PASSWORD_CHANGE, headers=_as_cookie(token)
    )

    _assert_generic_401(resp)
    assert await _password_hash(db_manager, user) == before


@pytest.mark.asyncio
async def test_red4_agent_bearer_cannot_export_tenant_data(api_client, db_manager, export_probe):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user)

    resp = await api_client.post("/api/v1/account/export", headers=_as_bearer(token))

    _assert_generic_401(resp)
    assert export_probe == []


@pytest.mark.asyncio
async def test_red4_agent_bearer_cannot_flip_headless_launch(api_client, db_manager):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user)

    resp = await api_client.put(
        "/api/v1/user/settings/headless-launch", json={"allow_headless_launch": True}, headers=_as_bearer(token)
    )

    _assert_generic_401(resp)
    readback = await api_client.get("/api/v1/user/settings/headless-launch", headers=_as_cookie(_browser_token(user)))
    assert readback.status_code == 200, readback.text
    assert readback.json()["allow_headless_launch"] is False


@pytest.mark.asyncio
async def test_agent_cookie_cannot_mint_an_api_key(api_client, db_manager):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user)

    resp = await api_client.post("/api/auth/api-keys", json={"name": "sec0046"}, headers=_as_cookie(token))

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_aud_less_agent_token_with_a_family_is_still_refused(api_client, db_manager):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user, audience=None)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}/password", json=_PASSWORD_CHANGE, headers=_as_cookie(token)
    )

    _assert_generic_401(resp)


@pytest.mark.asyncio
async def test_agent_cookie_cannot_be_refreshed_into_a_browser_session(api_client, db_manager):
    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user, audience=None)

    resp = await api_client.post("/api/auth/refresh", headers=_as_cookie(token))

    assert resp.status_code == 401, resp.text
    assert "access_token=" not in resp.headers.get("set-cookie", "")




@pytest.mark.asyncio
@pytest.mark.parametrize("carrier", ["query", "cookie"])
async def test_red5_websocket_handshake_refuses_agent_token(db_manager, carrier):
    from api.auth_utils import authenticate_websocket

    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user)
    ws = _FakeWebSocket(token=token) if carrier == "query" else _FakeWebSocket()
    if carrier == "cookie":
        ws.headers = {"cookie": f"access_token={token}", "host": "testserver", "origin": "http://testserver"}

    async with db_manager.get_session_async() as db:
        with pytest.raises(WebSocketException):
            await authenticate_websocket(ws, db=db)




@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/oauth/authorize", _consent_body("mcp:read")),
        ("post", "/api/oauth/authorize/deny", _consent_body("mcp:read")),
        ("put", "/api/v1/user/settings/headless-launch", {"allow_headless_launch": True}),
        ("post", "/api/v1/account/export", None),
    ],
)
async def test_browser_token_replayed_as_bearer_is_refused_on_dashboard_actions(
    api_client, db_manager, export_probe, method, path, body
):
    user = await _seed_user(db_manager)

    resp = await getattr(api_client, method)(path, json=body, headers=_as_bearer(_browser_token(user)))

    assert resp.status_code == 403, resp.text
    assert "browser session" in resp.text
    assert export_probe == []




@pytest.mark.asyncio
async def test_control_browser_cookie_still_grants_consent(api_client, db_manager):
    user = await _seed_user(db_manager)

    resp = await api_client.post(
        "/api/oauth/authorize",
        json=_consent_body("mcp:read mcp:write"),
        headers=_as_cookie(_browser_token(user)),
        follow_redirects=False,
    )

    assert resp.status_code == 200, resp.text
    assert "code=" in resp.json()["redirect_uri"]


@pytest.mark.asyncio
async def test_control_browser_cookie_still_denies_consent(api_client, db_manager):
    user = await _seed_user(db_manager)

    resp = await api_client.post(
        "/api/oauth/authorize/deny", json=_consent_body("mcp:read"), headers=_as_cookie(_browser_token(user))
    )

    assert resp.status_code == 200, resp.text
    assert "error=access_denied" in resp.json()["redirect_uri"]


@pytest.mark.asyncio
async def test_control_browser_cookie_still_sets_password(api_client, db_manager):
    user = await _seed_user(db_manager)
    before = await _password_hash(db_manager, user)

    resp = await api_client.put(
        f"/api/v1/users/{user['id']}/password", json=_PASSWORD_CHANGE, headers=_as_cookie(_browser_token(user))
    )

    assert resp.status_code == 200, resp.text
    assert await _password_hash(db_manager, user) != before


@pytest.mark.asyncio
async def test_control_browser_cookie_still_flips_headless_launch(api_client, db_manager):
    user = await _seed_user(db_manager)

    resp = await api_client.put(
        "/api/v1/user/settings/headless-launch",
        json={"allow_headless_launch": True},
        headers=_as_cookie(_browser_token(user)),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["allow_headless_launch"] is True


@pytest.mark.asyncio
async def test_control_browser_cookie_still_reaches_export(api_client, db_manager, export_probe):
    user = await _seed_user(db_manager)

    resp = await api_client.post("/api/v1/account/export", headers=_as_cookie(_browser_token(user)))

    assert resp.status_code == _EXPORT_REACHED, resp.text
    assert export_probe == [user["tenant_key"]]


@pytest.mark.asyncio
async def test_control_browser_cookie_still_mints_an_api_key(api_client, db_manager):
    user = await _seed_user(db_manager)

    resp = await api_client.post(
        "/api/auth/api-keys", json={"name": "sec0046"}, headers=_as_cookie(_browser_token(user))
    )

    assert resp.status_code in (200, 201), resp.text


@pytest.mark.asyncio
async def test_control_browser_cookie_still_opens_the_websocket(db_manager):
    from api.auth_utils import authenticate_websocket

    user = await _seed_user(db_manager)
    async with db_manager.get_session_async() as db:
        result = await authenticate_websocket(_FakeWebSocket(token=_browser_token(user)), db=db)

    assert result["authenticated"] is True
    assert result["user"]["tenant_key"] == user["tenant_key"]


@pytest.mark.asyncio
async def test_control_the_same_agent_token_still_works_on_mcp(db_manager):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    user = await _seed_user(db_manager)
    token = await _agent_token(db_manager, user)
    prior = state.db_manager
    state.db_manager = db_manager
    try:
        status, inner_reached = await _drive_mcp(MCPAuthMiddleware, token=token, db_manager=db_manager)
    finally:
        state.db_manager = prior

    assert status == 200
    assert inner_reached is True
