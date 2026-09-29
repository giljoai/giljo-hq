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

FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"

_TrustedNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class _PeerLike(Protocol):
    host: str


class _HeadersLike(Protocol):
    def get(self, key: str) -> str | None: ...


class _RequestLike(Protocol):

    @property
    def client(self) -> _PeerLike | None: ...

    @property
    def headers(self) -> _HeadersLike: ...


def parse_trusted_proxies(raw: str | None) -> list[_TrustedNetwork]:
    if not raw:
        return []
    networks: list[_TrustedNetwork] = []
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("Ignoring malformed %s entry: %r", TRUSTED_PROXIES_ENV, candidate)
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
        client = request.client
        peer_ip = client.host if client is not None else None

        if self._proxy_headers_always_trust:
            resolved = self._resolve_behind_always_trust(request)
            if resolved is not None:
                return resolved
            return peer_ip or "unknown"

        if client is None:
            return "unknown"

        if self.peer_is_trusted_proxy(peer_ip):
            cf_ip = request.headers.get("CF-Connecting-IP")
            if cf_ip and cf_ip.strip():
                return cf_ip.strip()
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                first_hop = forwarded.split(",")[0].strip()
                if first_hop:
                    return first_hop
        return peer_ip

    def _resolve_behind_always_trust(self, request: _RequestLike) -> str | None:
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
        for hop in reversed(forwarded.split(",")):
            candidate = hop.strip()
            if candidate and not self.peer_is_trusted_proxy(candidate):
                return candidate
        return None
