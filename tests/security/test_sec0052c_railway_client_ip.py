# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import re

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api.middleware import auth_rate_limiter as arl
from giljo_mcp.services.cache_backends import reset_registry_for_tests


CLIENT = "203.0.113.10"
RAILWAY_EDGE = "152.233.47.68"
CLOUDFLARE_EDGE = "172.68.1.1"
RAILWAY_PEER = "100.64.0.2"
SPOOFS = {
    "CF-Connecting-IP": "198.51.100.66",
    "Forwarded": "for=198.51.100.67",
    "True-Client-IP": "198.51.100.68",
    "X-Envoy-External-Address": "198.51.100.69",
}


def _edge_app():
    from api.middleware._proxy_aware_ip import ProxyAwareIpResolver
    from api.middleware.trusted_proxy_headers import TrustedProxyHeadersMiddleware

    app = FastAPI()

    @app.get("/who")
    async def who(request: Request):
        ip, from_header = ProxyAwareIpResolver().resolve_with_origin(request)
        return {"ip": ip, "from_header": from_header}

    @app.get("/limited")
    async def limited(request: Request):
        await arl.get_rate_limiter().check_rate_limit(request, limit=1, window=60, raise_on_limit=True)
        return {"ok": True}

    return ProxyHeadersMiddleware(TrustedProxyHeadersMiddleware(app), trusted_hosts="*")


async def _who(headers: dict) -> dict:
    transport = ASGITransport(app=_edge_app(), client=(RAILWAY_PEER, 4242))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.get("/who", headers=headers)).json()


@pytest.fixture
def prod_env(monkeypatch):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setenv("GILJO_TRUSTED_PROXIES", "100.64.0.0/10")
    monkeypatch.delenv("GILJO_CLIENT_IP_MODE", raising=False)
    monkeypatch.delenv("GILJO_CLIENT_IP_DEBUG", raising=False)
    return monkeypatch


DIRECT_SHAPE = {"X-Forwarded-For": f"{CLIENT}, {RAILWAY_EDGE}", "X-Real-IP": CLIENT, **SPOOFS}


@pytest.mark.asyncio
async def test_observed_prod_shape_resolves_to_the_client_in_railway_mode(prod_env):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    assert await _who(DIRECT_SHAPE) == {"ip": CLIENT, "from_header": True}


@pytest.mark.asyncio
async def test_observed_prod_shape_keys_on_the_railway_edge_with_mode_off(prod_env):
    assert (await _who(DIRECT_SHAPE))["ip"] == RAILWAY_EDGE


@pytest.mark.asyncio
async def test_hypothesis_a_cloudflare_x_real_ip_reads_cf_connecting_ip(prod_env):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    headers = {
        "X-Forwarded-For": f"{CLOUDFLARE_EDGE}, {RAILWAY_EDGE}",
        "X-Real-IP": CLOUDFLARE_EDGE,
        "CF-Connecting-IP": CLIENT,
    }
    assert (await _who(headers))["ip"] == CLIENT


@pytest.mark.asyncio
async def test_hypothesis_b_x_real_ip_already_the_client(prod_env):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    headers = {"X-Forwarded-For": f"{CLIENT}, {RAILWAY_EDGE}", "X-Real-IP": CLIENT, "CF-Connecting-IP": CLIENT}
    assert (await _who(headers))["ip"] == CLIENT


@pytest.mark.asyncio
async def test_shape_c_through_cloudflare_resolves_to_the_visitor(prod_env):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    headers = {"X-Forwarded-For": f"{CLOUDFLARE_EDGE}, {RAILWAY_EDGE}", "X-Real-IP": CLIENT, "CF-Connecting-IP": CLIENT}
    assert await _who(headers) == {"ip": CLIENT, "from_header": True}


@pytest.mark.asyncio
async def test_shape_c_direct_ignores_a_forged_public_cf_connecting_ip(prod_env):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    headers = {"X-Forwarded-For": f"{CLIENT}, {RAILWAY_EDGE}", "X-Real-IP": CLIENT, "CF-Connecting-IP": "1.1.1.1"}
    assert await _who(headers) == {"ip": CLIENT, "from_header": True}


@pytest.mark.asyncio
async def test_cloudflare_x_real_ip_without_a_valid_cf_header_keys_on_x_real_ip(prod_env):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    headers = {"X-Forwarded-For": f"{CLOUDFLARE_EDGE}, {RAILWAY_EDGE}", "X-Real-IP": CLOUDFLARE_EDGE}
    assert (await _who(headers))["ip"] == CLOUDFLARE_EDGE
    headers["CF-Connecting-IP"] = "not-an-address"
    assert (await _who(headers))["ip"] == CLOUDFLARE_EDGE


@pytest.mark.asyncio
@pytest.mark.parametrize("x_real_ip", [None, "", "not-an-address"])
async def test_missing_or_invalid_x_real_ip_falls_back_to_the_default_resolver(prod_env, x_real_ip):
    headers = {"X-Forwarded-For": f"{CLIENT}, {RAILWAY_EDGE}", **SPOOFS}
    if x_real_ip is not None:
        headers["X-Real-IP"] = x_real_ip
    default = await _who(headers)
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    assert await _who(headers) == default


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "cloudflare", "RAILWAY-ish", "1"])
async def test_any_other_mode_value_keeps_the_default_resolver(prod_env, value):
    default = await _who(DIRECT_SHAPE)
    prod_env.setenv("GILJO_CLIENT_IP_MODE", value)
    assert await _who(DIRECT_SHAPE) == default


@pytest.mark.asyncio
async def test_header_derived_loopback_is_never_exempt_in_railway_mode(prod_env, real_auth_rate_limiter):
    prod_env.setenv("GILJO_CLIENT_IP_MODE", "railway")
    reset_registry_for_tests()
    arl._RateLimiterHolder.reset_for_tests()
    try:
        transport = ASGITransport(app=_edge_app(), client=(RAILWAY_PEER, 4242))
        headers = {"X-Forwarded-For": f"127.0.0.1, {RAILWAY_EDGE}", "X-Real-IP": "127.0.0.1"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses = [(await client.get("/limited", headers=headers)).status_code for _ in range(2)]
    finally:
        reset_registry_for_tests()
        arl._RateLimiterHolder.reset_for_tests()
    assert statuses == [200, 429]


_ADDRESS = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,}")


def _debug_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("client-ip debug")]


@pytest.mark.asyncio
async def test_debug_line_names_classes_and_never_an_address(prod_env, caplog):
    prod_env.setenv("GILJO_CLIENT_IP_DEBUG", "1")
    headers = {
        "X-Forwarded-For": f"{CLOUDFLARE_EDGE}, 8.8.8.8, 100.64.9.9, 127.0.0.1, junk, {RAILWAY_EDGE}",
        "X-Real-IP": CLOUDFLARE_EDGE,
        "CF-Connecting-IP": CLIENT,
    }
    with caplog.at_level(logging.INFO, logger="api.middleware.trusted_proxy_headers"):
        await _who(headers)
    (line,) = _debug_lines(caplog)
    assert line == (
        "client-ip debug: x-real-ip=cloudflare "
        "xff=[cloudflare,public,private,loopback,invalid,railway-edge-prefix] cf-connecting-ip=present "
        "xri_eq_cf=false xri_eq_xff0=true"
    )
    assert not _ADDRESS.search(line), line


@pytest.mark.asyncio
async def test_debug_line_absent_when_the_variable_is_unset(prod_env, caplog):
    with caplog.at_level(logging.INFO, logger="api.middleware.trusted_proxy_headers"):
        await _who(DIRECT_SHAPE)
    assert _debug_lines(caplog) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            {"X-Forwarded-For": f"{CLOUDFLARE_EDGE}, {RAILWAY_EDGE}", "X-Real-IP": CLIENT, "CF-Connecting-IP": CLIENT},
            "xri_eq_cf=true xri_eq_xff0=false",
        ),
        (
            {"X-Forwarded-For": f"{CLIENT}, {RAILWAY_EDGE}", "X-Real-IP": CLIENT},
            "xri_eq_cf=na xri_eq_xff0=true",
        ),
        (
            {
                "X-Forwarded-For": f"{CLOUDFLARE_EDGE}, {RAILWAY_EDGE}",
                "X-Real-IP": "8.8.8.8",
                "CF-Connecting-IP": CLIENT,
            },
            "xri_eq_cf=false xri_eq_xff0=false",
        ),
        ({"CF-Connecting-IP": "junk"}, "xri_eq_cf=na xri_eq_xff0=na"),
    ],
)
async def test_debug_line_says_whether_x_real_ip_equals_cf_and_first_hop(prod_env, caplog, headers, expected):
    prod_env.setenv("GILJO_CLIENT_IP_DEBUG", "1")
    with caplog.at_level(logging.INFO, logger="api.middleware.trusted_proxy_headers"):
        await _who(headers)
    (line,) = _debug_lines(caplog)
    assert line.endswith(" " + expected), line
    assert not _ADDRESS.search(line), line
