# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import bcrypt
import pytest
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware import auth_rate_limiter as arl
from giljo_mcp.services.cache_backends import reset_registry_for_tests
from giljo_mcp.services.login_lockout_service import MAX_FAILED_ATTEMPTS


_LOGIN = "/api/auth/login"
_PASSWORD = "correct-horse-1"


@pytest.fixture
def fresh_limiters(monkeypatch):
    monkeypatch.delenv(arl._TRUSTED_PROXIES_ENV, raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    yield
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()


def _client(app, ip: str) -> HTTPXAsyncClient:
    return HTTPXAsyncClient(transport=ASGITransport(app=app, client=(ip, 4242)), base_url="http://test")


async def _seed_user(db_manager) -> str:
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        org = Organization(name=f"F68 Org {suffix}", slug=f"f68-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()
        session.add(
            User(
                username=f"f68_{suffix}",
                email=f"f68_{suffix}@example.com",
                password_hash=bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt()).decode(),
                tenant_key=tenant_key,
                role="developer",
                org_id=org.id,
            )
        )
        await session.commit()
    return f"f68_{suffix}"


async def _first_429(client, username: str, *, attempts: int):
    for _ in range(attempts):
        resp = await client.post(_LOGIN, json={"username": username, "password": "wrong-password-1"})
        if resp.status_code == 429:
            return resp
        assert resp.status_code == 401, resp.text
    raise AssertionError("no 429 within the attempt budget")


def _shape(resp) -> dict:
    return {
        "status": resp.status_code,
        "body": {k: v for k, v in resp.json().items() if k != "timestamp"},
        "headers": sorted(
            k for k in resp.headers if k.lower() in {"retry-after"} or k.lower().startswith("x-ratelimit")
        ),
    }


def _retry_after(resp) -> int:
    value = resp.headers["Retry-After"]
    assert re.fullmatch(r"\d+", value), value
    return int(value)


_LIMITERS = [
    ("per_address", {"GILJO_RL_LOGIN": "2", "GILJO_RL_LOGIN_ACCOUNT": "1000"}, 3, 60),
    (
        "per_account_hold",
        {"GILJO_RL_LOGIN": "1000", "GILJO_RL_LOGIN_ACCOUNT": "1", "GILJO_LOGIN_PER_ADDRESS_PAST_CEILING": "on"},
        3,
        300,
    ),
    (
        "account_and_address_lockout",
        {"GILJO_RL_LOGIN": "1000", "GILJO_RL_LOGIN_ACCOUNT": "1000"},
        MAX_FAILED_ATTEMPTS,
        900,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "env", "attempts", "max_seconds"), _LIMITERS, ids=[x[0] for x in _LIMITERS])
async def test_signin_429_carries_retry_after_and_hides_account_existence(
    name, env, attempts, max_seconds, api_client, db_manager, monkeypatch, real_auth_rate_limiter, fresh_limiters
):
    from api.app import app

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    real_user = await _seed_user(db_manager)
    unknown_user = f"nobody_{uuid4().hex[:8]}"

    async with _client(app, "203.0.113.11") as client:
        existing = await _first_429(client, real_user, attempts=attempts)
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    async with _client(app, "203.0.113.12") as client:
        missing = await _first_429(client, unknown_user, attempts=attempts)

    for resp in (existing, missing):
        assert 1 <= _retry_after(resp) <= max_seconds
    assert _shape(existing) == _shape(missing), f"{name}: the 429 differs between a real and an unknown account"
    print(
        f"RAW {name}: existing={_shape(existing)} retry-after={existing.headers['Retry-After']}; "
        f"unknown={_shape(missing)} retry-after={missing.headers['Retry-After']}"
    )


@pytest.mark.asyncio
async def test_cors_exposes_retry_after_to_a_cross_origin_dashboard(api_client):
    from api.app import app

    async with _client(app, "203.0.113.20") as client:
        resp = await client.get("/health", headers={"Origin": "http://localhost:7274"})

    exposed = [h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",")]
    assert "retry-after" in exposed, resp.headers


_SIGN_IN_WAIT_JS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "signInWait.js"
_LOCKING_MESSAGE = "Too many failed login attempts. Your account is temporarily locked."
_WHILE_LOCKED_MESSAGE = "Too many failed login attempts. Try again later."


def _locked_message_prefix() -> str:
    found = re.search(r"LOCKED_MESSAGE_PREFIX\s*=\s*'([^']+)'", _SIGN_IN_WAIT_JS.read_text())
    assert found, f"LOCKED_MESSAGE_PREFIX not found in {_SIGN_IN_WAIT_JS}; the sign-in page's lock match moved"
    return found.group(1)


@pytest.mark.asyncio
async def test_locked_account_messages_keep_the_prefix_the_signin_page_matches(
    api_client, db_manager, monkeypatch, real_auth_rate_limiter, fresh_limiters
):
    from api.app import app

    monkeypatch.setenv("GILJO_RL_LOGIN", "1000")
    monkeypatch.setenv("GILJO_RL_LOGIN_ACCOUNT", "1000")
    user = await _seed_user(db_manager)

    async with _client(app, "203.0.113.31") as client:
        locking = await _first_429(client, user, attempts=MAX_FAILED_ATTEMPTS)
        while_locked = await client.post(_LOGIN, json={"username": user, "password": "wrong-password-1"})

    assert while_locked.status_code == 429
    prefix = _locked_message_prefix().casefold()
    messages = [locking.json()["message"], while_locked.json()["message"]]
    assert messages == [_LOCKING_MESSAGE, _WHILE_LOCKED_MESSAGE]
    for message in messages:
        assert message.casefold().startswith(prefix), (message, prefix)


def test_generic_locked_account_handler_keeps_the_error_code_the_page_matches():
    handlers = (Path(__file__).resolve().parents[2] / "api" / "exception_handlers.py").read_text()
    page = _SIGN_IN_WAIT_JS.read_text()
    assert '"error_code": "ACCOUNT_LOCKED"' in handlers
    assert "LOCKED_ERROR_CODE = 'ACCOUNT_LOCKED'" in page
