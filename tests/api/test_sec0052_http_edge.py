# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient

from api.middleware import auth_rate_limiter as arl
from giljo_mcp.services.cache_backends import reset_registry_for_tests


def _client(app, *, ip: str = "198.51.100.77", base_url: str = "http://test") -> HTTPXAsyncClient:
    return HTTPXAsyncClient(transport=ASGITransport(app=app, client=(ip, 4242)), base_url=base_url)


def _wired_app(monkeypatch) -> FastAPI:
    import api.wiring.middleware as wiring

    monkeypatch.setattr("api.app.GILJO_MODE", "", raising=False)
    app = FastAPI()

    @app.get("/api/probe")
    async def probe():
        return {"ok": True}

    @app.post("/api/auth/login")
    async def echo_len(request: Request):
        return {"received": len(await request.body())}

    @app.post("/api/auth/register")
    async def register_stub():
        return {"ok": True}

    wiring.configure_middleware(app)
    return app


@pytest.fixture
def fresh_limiters(monkeypatch):
    monkeypatch.delenv(arl._TRUSTED_PROXIES_ENV, raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    yield
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()




@pytest.mark.asyncio
async def test_long_hostile_query_value_is_cheap(api_client):
    hostile = "drop " * 6600
    await api_client.get("/health")
    started = time.perf_counter()
    await api_client.get("/health", params={"q": hostile})
    elapsed = time.perf_counter() - started
    assert elapsed < 0.15, f"32 KB hostile query took {elapsed * 1000:.0f} ms"


@pytest.mark.asyncio
async def test_limiter_counts_requests_the_input_filter_rejects(monkeypatch, real_rate_limiter, fresh_limiters):
    monkeypatch.setenv("API_RATE_LIMIT", "2")
    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    app = _wired_app(monkeypatch)
    async with _client(app) as client:
        statuses = [(await client.get("/api/probe", params={"q": "<script>x</script>"})).status_code for _ in range(3)]
    assert statuses == [400, 400, 429]


@pytest.mark.asyncio
async def test_ordinary_text_with_sql_words_is_not_refused(api_client):
    response = await api_client.get("/health", params={"q": "union select from the backlog"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_script_tag_in_query_is_still_refused(api_client):
    response = await api_client.get("/health", params={"q": "<script>alert(1)</script>"})
    assert response.status_code == 400




async def _drain_app(scope, receive, send):
    total = 0
    while True:
        message = await receive()
        total += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    body = str(total).encode()
    await send(
        {"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode())]}
    )
    await send({"type": "http.response.body", "body": body})


async def _run(middleware, *, path: str, chunks: list[bytes], content_length: int | None):
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    pending = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1} for i, chunk in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


@pytest.mark.asyncio
async def test_body_cap_rejects_declared_oversize():
    from api.middleware.edge_guards import BodySizeLimitMiddleware

    cap = BodySizeLimitMiddleware(_drain_app, default_max_bytes=1000)
    assert await _run(cap, path="/api/x", chunks=[b"a" * 10], content_length=1001) == 413


@pytest.mark.asyncio
async def test_body_cap_rejects_chunked_oversize_without_content_length():
    from api.middleware.edge_guards import BodySizeLimitMiddleware

    cap = BodySizeLimitMiddleware(_drain_app, default_max_bytes=1000)
    assert await _run(cap, path="/api/x", chunks=[b"a" * 600, b"a" * 600], content_length=None) == 413


@pytest.mark.asyncio
async def test_body_cap_passes_a_body_at_the_limit():
    from api.middleware.edge_guards import BodySizeLimitMiddleware

    cap = BodySizeLimitMiddleware(_drain_app, default_max_bytes=1000)
    assert await _run(cap, path="/api/x", chunks=[b"a" * 500, b"a" * 500], content_length=None) == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/v1/products/abc/vision"), ("POST", "/api/vision-documents/"), ("PUT", "/api/vision-documents/d1")],
)
async def test_vision_upload_routes_get_the_upload_limit(method, path):
    from api.middleware.edge_guards import BodySizeLimitMiddleware

    cap = BodySizeLimitMiddleware(_drain_app, default_max_bytes=1_048_576)
    size = 3 * 1_048_576
    scope_path = path
    headers = [(b"content-length", str(size).encode())]
    sent: list[dict] = []
    pending = [{"type": "http.request", "body": b"a" * size, "more_body": False}]

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await cap({"type": "http", "method": method, "path": scope_path, "headers": headers}, receive, send)
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_real_app_answers_413_for_an_oversize_rest_body(api_client):
    response = await api_client.post(
        "/health", content=b"x" * (2 * 1_048_576), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_wired_app_counts_a_chunked_body(monkeypatch):
    app = _wired_app(monkeypatch)

    async def chunks():
        for _ in range(20):
            yield b"x" * 100_000

    async with _client(app) as client:
        response = await client.post("/api/auth/login", content=chunks())
    assert response.status_code == 413




def _stub_request(*, client_host: str = "192.0.2.9", headers: dict | None = None, path: str = "/api/auth/login"):
    values = headers or {}
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host),
        headers=SimpleNamespace(get=values.get),
        url=SimpleNamespace(path=path),
    )


@pytest.mark.asyncio
async def test_policies_from_one_ip_keep_separate_counters(real_auth_rate_limiter, fresh_limiters):
    limiter = arl.RateLimiter()
    request = _stub_request()
    results = [await limiter.check_rate_limit(request, limit=2, policy="oauth_token") for _ in range(3)]
    assert results == [True, True, False]
    assert await limiter.check_rate_limit(request, limit=2, policy="login") is True


@pytest.mark.asyncio
async def test_unnamed_policy_falls_back_to_the_route(real_auth_rate_limiter, fresh_limiters):
    limiter = arl.RateLimiter()
    first = _stub_request(path="/api/oauth/register")
    second = _stub_request(path="/api/auth/login")
    assert [await limiter.check_rate_limit(first, limit=1) for _ in range(2)] == [True, False]
    assert await limiter.check_rate_limit(second, limit=1) is True




def _resolver(monkeypatch, trusted: str):
    from api.middleware._proxy_aware_ip import ProxyAwareIpResolver

    monkeypatch.setenv("GILJO_TRUSTED_PROXIES", trusted)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    return ProxyAwareIpResolver()


def test_same_box_proxy_cannot_be_fed_a_leftmost_loopback(monkeypatch):
    resolver = _resolver(monkeypatch, "127.0.0.1")
    request = _stub_request(client_host="127.0.0.1", headers={"X-Forwarded-For": "127.0.0.1, 203.0.113.5"})
    assert resolver.resolve(request) == "203.0.113.5"


def test_trusted_lan_range_keeps_each_lan_client_apart(monkeypatch):
    resolver = _resolver(monkeypatch, "192.0.2.0/24")
    request = _stub_request(client_host="192.0.2.5", headers={"X-Forwarded-For": "192.0.2.20"})
    assert resolver.resolve(request) == "192.0.2.20"


def test_cf_connecting_ip_ignored_behind_a_non_cloudflare_proxy(monkeypatch):
    resolver = _resolver(monkeypatch, "127.0.0.1")
    request = _stub_request(
        client_host="127.0.0.1", headers={"CF-Connecting-IP": "127.0.0.1", "X-Forwarded-For": "203.0.113.5"}
    )
    assert resolver.resolve(request) == "203.0.113.5"


def test_cf_connecting_ip_honoured_from_a_cloudflare_peer(monkeypatch):
    resolver = _resolver(monkeypatch, "173.245.48.0/20")
    request = _stub_request(
        client_host="173.245.48.10", headers={"CF-Connecting-IP": "203.0.113.38", "X-Forwarded-For": "203.0.113.38"}
    )
    assert resolver.resolve(request) == "203.0.113.38"


def test_cf_connecting_ip_honoured_when_the_proxy_saw_a_cloudflare_hop(monkeypatch):
    resolver = _resolver(monkeypatch, "127.0.0.1")
    request = _stub_request(
        client_host="127.0.0.1",
        headers={"CF-Connecting-IP": "203.0.113.38", "X-Forwarded-For": "6.6.6.6, 203.0.113.38, 172.68.54.64"},
    )
    assert resolver.resolve(request) == "203.0.113.38"


def _edge_probe_app():
    from api.middleware.trusted_proxy_headers import TrustedProxyHeadersMiddleware

    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request):
        await arl.get_rate_limiter().check_rate_limit(request, limit=1, window=60, raise_on_limit=True)
        return {"ok": True}

    return TrustedProxyHeadersMiddleware(app)


@pytest.mark.asyncio
async def test_header_derived_loopback_is_not_exempt(monkeypatch, real_auth_rate_limiter, fresh_limiters):
    monkeypatch.setenv("GILJO_TRUSTED_PROXIES", "192.0.2.5")
    app = _edge_probe_app()
    async with _client(app, ip="192.0.2.5") as client:
        statuses = [
            (await client.get("/probe", headers={"X-Forwarded-For": "127.0.0.1"})).status_code for _ in range(2)
        ]
    assert statuses == [200, 429]


@pytest.mark.asyncio
async def test_direct_loopback_operator_is_still_exempt(monkeypatch, real_auth_rate_limiter, fresh_limiters):
    app = _edge_probe_app()
    async with _client(app, ip="127.0.0.1") as client:
        statuses = [(await client.get("/probe")).status_code for _ in range(3)]
    assert statuses == [200, 200, 200]




@pytest.mark.asyncio
async def test_switch_on_spray_holds_each_address_to_one_attempt(
    api_client, monkeypatch, real_auth_rate_limiter, fresh_limiters
):
    from api.app import app

    monkeypatch.setenv("GILJO_RL_LOGIN_ACCOUNT", "3")
    monkeypatch.setenv("GILJO_LOGIN_PER_ADDRESS_PAST_CEILING", "on")
    victim = f"victim_{uuid4().hex[:8]}"
    body = {"username": victim, "password": "wrong-password-1"}

    async def attempt(ip: str) -> int:
        async with _client(app, ip=ip) as client:
            return (await client.post("/api/auth/login", json=body)).status_code

    spray = [await attempt(f"203.0.113.{n}") for n in (1, 2, 3)]
    assert spray == [401, 401, 401]
    assert await attempt("203.0.113.4") == 401
    assert await attempt("203.0.113.4") == 429
    assert await attempt("198.51.100.20") == 401
    other = {"username": f"other_{uuid4().hex[:8]}", "password": "wrong-password-1"}
    async with _client(app, ip="203.0.113.4") as client:
        assert (await client.post("/api/auth/login", json=other)).status_code == 401


async def _seed_login_user(db_manager, password: str) -> str:
    import bcrypt

    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.tenant import TenantManager

    suffix = uuid4().hex[:8]
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        org = Organization(
            name=f"Ceiling Org {suffix}", slug=f"ceiling-{suffix}", tenant_key=tenant_key, is_active=True
        )
        session.add(org)
        await session.flush()
        session.add(
            User(
                username=f"owner_{suffix}",
                email=f"owner_{suffix}@example.com",
                password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                tenant_key=tenant_key,
                role="developer",
                org_id=org.id,
            )
        )
        await session.commit()
    return f"owner_{suffix}"


@pytest.mark.asyncio
async def test_switch_off_owner_signs_in_past_the_account_ceiling(
    api_client, db_manager, monkeypatch, caplog, real_auth_rate_limiter, fresh_limiters
):
    import logging

    from api.app import app

    monkeypatch.setenv("GILJO_RL_LOGIN_ACCOUNT", "3")
    monkeypatch.delenv("GILJO_LOGIN_PER_ADDRESS_PAST_CEILING", raising=False)
    owner = await _seed_login_user(db_manager, "correct-horse-1")

    async def attempt(ip: str, password: str) -> int:
        async with _client(app, ip=ip) as client:
            return (await client.post("/api/auth/login", json={"username": owner, "password": password})).status_code

    with caplog.at_level(logging.WARNING, logger="api.middleware.auth_rate_limiter"):
        assert [await attempt(f"203.0.113.{n}", "wrong-1") for n in (1, 2, 3, 4)] == [401, 401, 401, 401]
        assert await attempt("203.0.113.4", "wrong-1") == 401
        assert await attempt("203.0.113.4", "correct-horse-1") == 200

    ceiling_logs = [r.getMessage() for r in caplog.records if "ceiling" in r.getMessage().lower()]
    assert ceiling_logs, "crossing the account ceiling must log a warning"
    assert "attempts=6" in ceiling_logs[-1]
    assert owner not in "\n".join(ceiling_logs), "the identifier itself must not be logged"




def _csrf_app():
    from api.middleware.csrf import CSRFProtectionMiddleware

    app = FastAPI()

    @app.get("/api/thing")
    async def read_thing():
        return {"ok": True}

    @app.post("/api/thing")
    async def write_thing():
        return {"ok": True}

    app.add_middleware(CSRFProtectionMiddleware)
    return app


@pytest.mark.asyncio
async def test_csrf_compare_is_constant_time(monkeypatch):
    import secrets as secrets_module

    calls: list[tuple[str, str]] = []
    real = secrets_module.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(secrets_module, "compare_digest", spy)
    async with _client(_csrf_app()) as client:
        response = await client.post("/api/thing", headers={"X-CSRF-Token": "tok", "Cookie": "csrf_token=tok"})
    assert response.status_code == 200
    assert calls, "CSRF token compare did not use a constant-time compare"


@pytest.mark.asyncio
async def test_https_csrf_cookie_uses_the_host_prefix():
    async with _client(_csrf_app(), base_url="https://test") as client:
        response = await client.get("/api/thing")
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith("__Host-csrf_token=")
    assert "secure" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()
    assert "domain=" not in set_cookie.lower()


@pytest.mark.asyncio
async def test_plain_http_lan_install_keeps_the_plain_cookie_name():
    async with _client(_csrf_app()) as client:
        response = await client.get("/api/thing")
    assert response.headers["set-cookie"].startswith("csrf_token=")


@pytest.mark.asyncio
async def test_https_ignores_a_sibling_planted_plain_cookie():
    async with _client(_csrf_app(), base_url="https://test") as client:
        planted = await client.post("/api/thing", headers={"X-CSRF-Token": "evil", "Cookie": "csrf_token=evil"})
        genuine = await client.post("/api/thing", headers={"X-CSRF-Token": "good", "Cookie": "__Host-csrf_token=good"})
    assert planted.status_code == 403
    assert genuine.status_code == 200


@pytest.mark.asyncio
async def test_https_expires_a_leftover_plain_cookie():
    async with _client(_csrf_app(), base_url="https://test") as client:
        response = await client.get("/api/thing", headers={"Cookie": "csrf_token=old"})
    set_cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("__Host-csrf_token=") for c in set_cookies)
    assert any(c.startswith("csrf_token=") and "max-age=0" in c.lower() for c in set_cookies)


@pytest.mark.asyncio
async def test_cookie_authenticated_register_requires_csrf(monkeypatch):
    app = _wired_app(monkeypatch)
    async with _client(app) as client:
        response = await client.post("/api/auth/register", json={}, headers={"Cookie": "access_token=x"})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


@pytest.mark.asyncio
async def test_claude_origins_get_no_credentialed_rest_cors(api_client):
    response = await api_client.options(
        "/api/v1/products/",
        headers={"Origin": "https://claude.ai", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") != "https://claude.ai"


@pytest.mark.asyncio
async def test_claude_mcp_preflight_still_answered_without_credentials(api_client):
    response = await api_client.options(
        "/mcp",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, mcp-protocol-version",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://claude.ai"
    assert response.headers.get("access-control-allow-credentials") != "true"


_CONNECTOR_SIMPLE_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/api/oauth/register",
    "/api/oauth/token",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://claude.ai", "https://claude.com"])
@pytest.mark.parametrize("path", _CONNECTOR_SIMPLE_PATHS)
async def test_claude_simple_request_on_connector_path_carries_no_credentials(api_client, origin, path):
    response = await api_client.get(path, headers={"Origin": origin})
    assert response.headers.get("access-control-allow-origin") == origin
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _CONNECTOR_SIMPLE_PATHS)
async def test_claude_preflight_on_connector_path_is_unchanged(api_client, path):
    response = await api_client.options(
        path,
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://claude.ai"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
async def test_dashboard_origin_keeps_credentialed_cors(api_client):
    from api.app import app

    dashboard_origin = next(o for o in app.state.cors_origins if o.startswith("http"))
    response = await api_client.get("/api/v1/projects/", headers={"Origin": dashboard_origin})
    assert response.headers.get("access-control-allow-origin") == dashboard_origin
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_claude_simple_request_on_dashboard_route_gets_no_acao(api_client):
    response = await api_client.get("/api/v1/projects/", headers={"Origin": "https://claude.ai"})
    assert "access-control-allow-origin" not in response.headers



_MIB = 1024 * 1024


def _json_body(size: int, *, name: str) -> bytes:
    shell = json.dumps({"name": name, "description": ""}, ensure_ascii=False).encode()
    filler_bytes = size - len(shell)
    text = "漢" * (filler_bytes // 3) + "a" * (filler_bytes % 3)
    body = json.dumps({"name": name, "description": text}, ensure_ascii=False).encode()
    assert len(body) == size
    return body


def _json_headers(auth_headers: dict) -> dict:
    return {**auth_headers, "Content-Type": "application/json"}


def _full_product_body(name: str) -> bytes:
    text = "\U00020000" * 20_000
    blocks = {
        "tech_stack": ("programming_languages", "frontend_frameworks", "backend_frameworks", "databases_storage"),
        "architecture": ("primary_pattern", "design_patterns", "api_style", "architecture_notes", "coding_conventions"),
        "test_config": ("quality_standards", "testing_frameworks"),
    }
    payload = {"name": name, "description": text, "core_features": text, "brand_guidelines": text}
    payload.update({block: dict.fromkeys(fields, text) for block, fields in blocks.items()})
    payload["tech_stack"].update(infrastructure=text, dev_tools=text)
    body = json.dumps(payload, ensure_ascii=False).encode()
    assert _MIB < len(body) < 2 * _MIB
    return body


@pytest.mark.asyncio
async def test_long_non_latin_product_create_and_update_are_accepted(api_client, auth_headers):
    created = await api_client.post(
        "/api/v1/products/", content=_full_product_body("Long CJK"), headers=_json_headers(auth_headers)
    )
    assert created.status_code == 200, created.text[:200]
    updated = await api_client.put(
        f"/api/v1/products/{created.json()['id']}",
        content=_full_product_body("Long CJK 2"),
        headers=_json_headers(auth_headers),
    )
    assert updated.status_code == 200, updated.text[:200]


@pytest.mark.asyncio
async def test_product_update_over_two_mib_is_refused_declared_and_chunked(api_client, auth_headers):
    body = _json_body(2 * _MIB + 1, name="Too big")
    declared = await api_client.put("/api/v1/products/p1", content=body, headers=_json_headers(auth_headers))
    assert declared.status_code == 413

    async def chunks():
        for start in range(0, len(body), 256 * 1024):
            yield body[start : start + 256 * 1024]

    chunked = await api_client.put("/api/v1/products/p1", content=chunks(), headers=_json_headers(auth_headers))
    assert chunked.status_code == 413


@pytest.mark.asyncio
async def test_non_product_route_keeps_the_one_mib_default(api_client, auth_headers):
    response = await api_client.post(
        "/api/v1/projects/", content=_json_body(_MIB + 1, name="Not a product"), headers=_json_headers(auth_headers)
    )
    assert response.status_code == 413
