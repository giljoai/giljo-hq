# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ipaddress
import logging
import os

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from ._cloudflare_ip_ranges import is_cloudflare_edge_ip
from ._proxy_aware_ip import (
    CLIENT_FROM_HEADER_SCOPE_KEY,
    FORWARDED_ALLOW_IPS_ENV,
    ProxyAwareIpResolver,
    split_trusted_proxies,
)


logger = logging.getLogger(__name__)


_DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1"
_SCHEMES = {"http", "https", "ws", "wss"}


CLIENT_IP_DEBUG_ENV = "GILJO_CLIENT_IP_DEBUG"

_RAILWAY_EDGE_PREFIXES = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("152.233.0.0/16", "79.127.0.0/16", "89.222.0.0/16", "84.17.0.0/16", "46.151.0.0/16", "95.173.0.0/16")
)


def _address_class(raw: str | None) -> str:
    try:
        addr = ipaddress.ip_address((raw or "").strip())
    except ValueError:
        return "invalid"
    if addr.is_loopback:
        return "loopback"
    if is_cloudflare_edge_ip(str(addr)):
        return "cloudflare"
    if any(addr in network for network in _RAILWAY_EDGE_PREFIXES):
        return "railway-edge-prefix"
    if not addr.is_global:
        return "private"
    return "public"


def _parsed_ip(raw: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((raw or "").strip())
    except ValueError:
        return None


def _same_address(left: str | None, right: str | None) -> str:
    a, b = _parsed_ip(left), _parsed_ip(right)
    if a is None or b is None:
        return "na"
    return "true" if a == b else "false"


def _log_address_classes(headers: Headers) -> None:
    forwarded = headers.get("X-Forwarded-For")
    raw_hops = forwarded.split(",") if forwarded else []
    hops = [_address_class(hop) for hop in raw_hops]
    real_ip = headers.get("X-Real-IP")
    logger.info(
        "client-ip debug: x-real-ip=%s xff=[%s] cf-connecting-ip=%s xri_eq_cf=%s xri_eq_xff0=%s",
        _address_class(real_ip) if real_ip is not None else "absent",
        ",".join(hops),
        "present" if headers.get("CF-Connecting-IP") else "absent",
        _same_address(real_ip, headers.get("CF-Connecting-IP")),
        _same_address(real_ip, raw_hops[0] if raw_hops else None),
    )


class _Request:

    def __init__(self, scope: Scope) -> None:
        client = scope.get("client")
        self.client = _Peer(client[0]) if client else None
        self.headers = Headers(scope=scope)


class _Peer:
    def __init__(self, host: str) -> None:
        self.host = host


class TrustedProxyHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._resolver = ProxyAwareIpResolver()
        raw = os.getenv(FORWARDED_ALLOW_IPS_ENV, _DEFAULT_FORWARDED_ALLOW_IPS)
        entries = [entry.strip() for entry in raw.split(",")]
        self._proto_trust_all = "*" in entries
        self._proto_trusted, malformed = split_trusted_proxies(",".join(entry for entry in entries if entry != "*"))
        if malformed:
            logger.warning("Ignoring %d malformed FORWARDED_ALLOW_IPS entries", len(malformed))

    def _peer_may_set_scheme(self, peer_ip: str) -> bool:
        if self._proto_trust_all:
            return True
        try:
            addr = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        return any(addr in network for network in self._proto_trusted)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and scope.get("client"):
            peer_ip = scope["client"][0]
            request = _Request(scope)
            if scope["type"] == "http" and os.getenv(CLIENT_IP_DEBUG_ENV, "").strip() == "1":
                _log_address_classes(request.headers)
            if self._peer_may_set_scheme(peer_ip):
                proto = request.headers.get("X-Forwarded-Proto", "").strip()
                if proto in _SCHEMES:
                    scope["scheme"] = proto.replace("http", "ws") if scope["type"] == "websocket" else proto
            resolved = self._resolver.resolve(request)
            if resolved not in (peer_ip, "unknown"):
                scope["client"] = (resolved, 0)
                scope[CLIENT_FROM_HEADER_SCOPE_KEY] = True
        await self.app(scope, receive, send)
