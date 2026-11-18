# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import ipaddress
import logging
import os
from typing import Protocol

from ._cloudflare_ip_ranges import is_cloudflare_edge_ip


logger = logging.getLogger(__name__)


TRUSTED_PROXIES_ENV = "GILJO_TRUSTED_PROXIES"

CLIENT_IP_MODE_ENV = "GILJO_CLIENT_IP_MODE"
RAILWAY_CLIENT_IP_MODE = "railway"

CLIENT_FROM_HEADER_SCOPE_KEY = "giljo.client_from_forwarding_header"

FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"

_TrustedNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def railway_mode_enabled() -> bool:
    return os.getenv(CLIENT_IP_MODE_ENV, "").strip().lower() == RAILWAY_CLIENT_IP_MODE


def _valid_ip(raw: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address((raw or "").strip()))
    except ValueError:
        return None


class _PeerLike(Protocol):
    host: str


class _HeadersLike(Protocol):
    def get(self, key: str) -> str | None: ...


class _RequestLike(Protocol):

    @property
    def client(self) -> _PeerLike | None: ...

    @property
    def headers(self) -> _HeadersLike: ...


def split_trusted_proxies(raw: str | None) -> tuple[list[_TrustedNetwork], list[str]]:
    networks: list[_TrustedNetwork] = []
    malformed: list[str] = []
    for entry in (raw or "").split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            malformed.append(candidate)
    return networks, malformed


def parse_trusted_proxies(raw: str | None) -> list[_TrustedNetwork]:
    networks, malformed = split_trusted_proxies(raw)
    if malformed:
        logger.warning("Ignoring %d malformed GILJO_TRUSTED_PROXIES entries", len(malformed))
    return networks


class ProxyAwareIpResolver:

    def __init__(self) -> None:
        self._trusted_proxies = parse_trusted_proxies(os.getenv(TRUSTED_PROXIES_ENV))
        self._proxy_headers_always_trust = self._read_always_trust()

    @staticmethod
    def _read_always_trust() -> bool:
        raw = os.getenv(FORWARDED_ALLOW_IPS_ENV, "")
        return "*" in {entry.strip() for entry in raw.split(",")}

    @property
    def trusted_proxy_count(self) -> int:
        return len(self._trusted_proxies)

    def peer_is_trusted_proxy(self, peer_ip: str) -> bool:
        if not self._trusted_proxies:
            return False
        try:
            addr = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        return any(addr in network for network in self._trusted_proxies)

    def resolve(self, request: _RequestLike) -> str:
        return self.resolve_with_origin(request)[0]

    def resolve_with_origin(self, request: _RequestLike) -> tuple[str, bool]:
        if railway_mode_enabled():
            railway_client = self._resolve_railway(request)
            if railway_client is not None:
                return railway_client, True

        client = request.client
        peer_ip = client.host if client is not None else None
        scope = getattr(request, "scope", None) or {}
        rewritten_by_edge = bool(scope.get(CLIENT_FROM_HEADER_SCOPE_KEY))

        if self._proxy_headers_always_trust:
            resolved = self._resolve_from_trusted_chain(request)
            if resolved is not None:
                return resolved, True
            return peer_ip or "unknown", rewritten_by_edge

        if peer_ip is None:
            return "unknown", False

        if self.peer_is_trusted_proxy(peer_ip):
            cf_ip = (request.headers.get("CF-Connecting-IP") or "").strip()
            if cf_ip and is_cloudflare_edge_ip(peer_ip):
                return cf_ip, True
            resolved = self._resolve_from_trusted_chain(request)
            if resolved is not None:
                return resolved, True
        return peer_ip, rewritten_by_edge

    @staticmethod
    def _resolve_railway(request: _RequestLike) -> str | None:
        real_ip = _valid_ip(request.headers.get("X-Real-IP"))
        if real_ip is None:
            return None
        if is_cloudflare_edge_ip(real_ip):
            return _valid_ip(request.headers.get("CF-Connecting-IP")) or real_ip
        return real_ip

    def _resolve_from_trusted_chain(self, request: _RequestLike) -> str | None:
        nearest_untrusted_hop = self._nearest_untrusted_xff_hop(request)

        cf_ip = request.headers.get("CF-Connecting-IP")
        if (
            cf_ip
            and cf_ip.strip()
            and nearest_untrusted_hop is not None
            and is_cloudflare_edge_ip(nearest_untrusted_hop)
        ):
            return cf_ip.strip()

        return nearest_untrusted_hop

    def _nearest_untrusted_xff_hop(self, request: _RequestLike) -> str | None:
        forwarded = request.headers.get("X-Forwarded-For")
        if not forwarded:
            return None
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        for candidate in reversed(hops):
            if not self.peer_is_trusted_proxy(candidate):
                return candidate
        return hops[0] if hops else None
