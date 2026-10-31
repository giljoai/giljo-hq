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

from ._proxy_aware_ip import FORWARDED_ALLOW_IPS_ENV, ProxyAwareIpResolver, split_trusted_proxies


logger = logging.getLogger(__name__)


_DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1"
_SCHEMES = {"http", "https", "ws", "wss"}


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
            if self._peer_may_set_scheme(peer_ip):
                proto = request.headers.get("X-Forwarded-Proto", "").strip()
                if proto in _SCHEMES:
                    scope["scheme"] = proto.replace("http", "ws") if scope["type"] == "websocket" else proto
            resolved = self._resolver.resolve(request)
            if resolved not in (peer_ip, "unknown"):
                scope["client"] = (resolved, 0)
        await self.app(scope, receive, send)
