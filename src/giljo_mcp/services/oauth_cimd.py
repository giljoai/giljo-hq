# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import ssl
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from urllib.parse import SplitResult, urlsplit

import httpcore

from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

CIMD_MAX_DOCUMENT_BYTES = 16 * 1024
CIMD_FETCH_TIMEOUT_SECONDS = 5.0
CIMD_MAX_REDIRECT_URIS = 10
CIMD_MAX_REDIRECT_URI_LENGTH = 2048
CIMD_MAX_CLIENT_NAME_LENGTH = 200
CIMD_CACHE_MAX_ENTRIES = 256
CIMD_CACHE_DEFAULT_TTL_SECONDS = 300
CIMD_CACHE_MIN_TTL_SECONDS = 60
CIMD_CACHE_MAX_TTL_SECONDS = 3600
CIMD_STALE_MAX_SECONDS = 3600
CIMD_NEGATIVE_TTL_SECONDS = 45
CIMD_MAX_CONCURRENT_FETCHES = 8
CIMD_MAX_DNS_LOOKUPS = 8

_ALLOWED_PORTS: frozenset[int | None] = frozenset({None, 443})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MAX_AGE = re.compile(r"(?:^|[\s,])max-age=(\d+)(?:$|[\s,])", re.IGNORECASE)
_WHITESPACE_OR_CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f\u2028\u2029\\]")
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_EXTRA_BLOCKED_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in ("::/96", "fec0::/10", "192.88.99.0/24"))


class CimdError(ValueError):

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid_client: {reason}")


class CimdTransientError(CimdError):
    pass


@dataclass(frozen=True)
class FetchedDocument:
    status: int
    cache_control: str | None
    body: bytes


def _now() -> float:
    return time.monotonic()


def is_cimd_client_id(client_id: str) -> bool:
    return isinstance(client_id, str) and client_id.startswith(("https://", "http://"))


_LOG_HOST_LABELS: dict[str, str] = {
    "claude.ai": "claude",
    "chatgpt.com": "chatgpt",
    "vscode.dev": "vscode",
    "insiders.vscode.dev": "vscode-insiders",
    "opencode.ai": "opencode",
    "cursor.com": "cursor",
}


def _loggable(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    return _LOG_HOST_LABELS.get(host, "other")


def validate_client_id_url(client_id: str) -> SplitResult:
    if _WHITESPACE_OR_CONTROL.search(client_id):
        raise CimdError("client_id URL contains whitespace, control characters or a backslash")
    try:
        parts = urlsplit(client_id)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise CimdError("client_id is not a valid URL") from None
    if parts.scheme != "https":
        raise CimdError("client_id URL must use https")
    if not hostname:
        raise CimdError("client_id URL has no host")
    if not client_id.isascii():
        raise CimdError("client_id URL must be ASCII (use punycode for international hosts)")
    if parts.username is not None or parts.password is not None:
        raise CimdError("client_id URL must not carry credentials")
    if "#" in client_id:
        raise CimdError("client_id URL must not carry a fragment")
    if not parts.path:
        raise CimdError("client_id URL must have a path")
    if any(segment in (".", "..") for segment in parts.path.split("/")):
        raise CimdError("client_id URL must not contain dot segments")
    if port not in _ALLOWED_PORTS:
        raise CimdError("client_id URL must use the default https port")
    return parts


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            candidates.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            candidates.append(ip.sixtofour)
        if ip.teredo is not None:
            candidates.extend(ip.teredo)
        if ip in _NAT64_PREFIX:
            candidates.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return all(
        candidate.is_global
        and not candidate.is_multicast
        and not any(candidate in network for network in _EXTRA_BLOCKED_NETWORKS if network.version == candidate.version)
        for candidate in candidates
    )


_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=CIMD_MAX_DNS_LOOKUPS, thread_name_prefix="cimd-dns")
_dns_in_flight = 0


async def _lookup(host: str, port: int) -> list[str]:
    global _dns_in_flight  # noqa: PLW0603 - a process-wide bound on queued lookups
    if _dns_in_flight >= CIMD_MAX_DNS_LOOKUPS:
        raise CimdError("too many client metadata lookups in progress")
    _dns_in_flight += 1
    future = asyncio.get_running_loop().run_in_executor(
        _DNS_EXECUTOR, socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM
    )

    def _release(_: object) -> None:
        global _dns_in_flight  # noqa: PLW0603
        _dns_in_flight -= 1

    future.add_done_callback(_release)
    return [str(info[4][0]) for info in await future]


async def resolve_public_address(host: str, port: int) -> str:
    try:
        addresses = await _lookup(host, port)
    except OSError:
        raise CimdTransientError("client_id host did not resolve") from None
    if not addresses:
        raise CimdError("client_id host did not resolve")
    if not all(is_public_address(address) for address in addresses):
        raise CimdError("client_id host resolves to a non-public address")
    return addresses[0]


class _PinnedBackend(httpcore.AsyncNetworkBackend):

    def __init__(self, address: str) -> None:
        self._address = address
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return await self._inner.connect_tcp(
            self._address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise CimdError("unix sockets are not permitted")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _build_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _read_capped(chunks: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > CIMD_MAX_DOCUMENT_BYTES:
            raise CimdError("client metadata document is too large")
    return bytes(body)


async def fetch_document(url: str, parts: SplitResult, address: str) -> FetchedDocument:
    timeout = CIMD_FETCH_TIMEOUT_SECONDS
    headers = [
        (b"Host", parts.netloc.encode("ascii")),
        (b"Accept", b"application/json"),
        (b"Accept-Encoding", b"identity"),
        (b"User-Agent", b"GiljoHQ-CIMD/1"),
    ]
    extensions = {"timeout": {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout}}
    pool = httpcore.AsyncConnectionPool(
        ssl_context=_build_ssl_context(), network_backend=_PinnedBackend(address), max_connections=1
    )
    async with pool, pool.stream("GET", url, headers=headers, extensions=extensions) as response:
        if 300 <= response.status < 400:
            raise CimdError("client metadata URL redirected; redirects are not followed")
        if response.status != 200:
            error = CimdTransientError if response.status >= 500 else CimdError
            raise error(f"client metadata URL answered {response.status}")
        declared = _header(response.headers, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > CIMD_MAX_DOCUMENT_BYTES:
            raise CimdError("client metadata document is too large")
        body = await _read_capped(response.aiter_stream())
        return FetchedDocument(
            status=response.status, cache_control=_header(response.headers, b"cache-control"), body=body
        )


def _redirect_uri_allowed(uri: str) -> bool:
    if not uri or len(uri) > CIMD_MAX_REDIRECT_URI_LENGTH or _WHITESPACE_OR_CONTROL.search(uri) or "#" in uri:
        return False
    try:
        parts = urlsplit(uri)
        hostname = parts.hostname
    except ValueError:
        return False
    if not hostname or parts.username is not None or parts.password is not None:
        return False
    if parts.scheme == "http":
        return hostname.lower() in _LOOPBACK_HOSTS
    return parts.scheme == "https"


@dataclass(frozen=True)
class CimdClient:
    client_id: str
    client_name: str
    redirect_uris: list[str]


def parse_client_document(client_id: str, body: bytes) -> CimdClient:
    if len(body) > CIMD_MAX_DOCUMENT_BYTES:
        raise CimdError("client metadata document is too large")
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        raise CimdError("client metadata document is not valid JSON") from None
    if not isinstance(document, dict):
        raise CimdError("client metadata document must be a JSON object")
    if document.get("client_id") != client_id:
        raise CimdError("client metadata client_id does not match the URL it was fetched from")
    if "client_secret" in document or "client_secret_expires_at" in document:
        raise CimdError("client metadata must not carry a client secret")

    listed = document.get("redirect_uris")
    if not isinstance(listed, list) or not listed or not all(isinstance(uri, str) for uri in listed):
        raise CimdError("client metadata redirect_uris must be a non-empty list of strings")
    if len(listed) > CIMD_MAX_REDIRECT_URIS:
        raise CimdError("client metadata lists too many redirect URIs")
    redirect_uris = [uri for uri in listed if _redirect_uri_allowed(uri)]
    if not redirect_uris:
        raise CimdError("client metadata has no redirect URI this server accepts")

    name = document.get("client_name")
    display = sanitize(name).strip()[:CIMD_MAX_CLIENT_NAME_LENGTH] if isinstance(name, str) else ""
    return CimdClient(
        client_id=client_id,
        client_name=display or (urlsplit(client_id).hostname or client_id),
        redirect_uris=redirect_uris,
    )


def _loopback_key(uri: str) -> tuple[str, str, str] | None:
    if not uri or len(uri) > CIMD_MAX_REDIRECT_URI_LENGTH or _WHITESPACE_OR_CONTROL.search(uri) or "#" in uri:
        return None
    try:
        parts = urlsplit(uri)
        hostname = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    if parts.scheme != "http" or parts.username is not None or parts.password is not None:
        return None
    if hostname is None or hostname.lower() not in _LOOPBACK_HOSTS:
        return None
    return hostname.lower(), parts.path, parts.query


def redirect_uri_matches(listed: list[str], requested: str) -> bool:
    if requested in listed:
        return True
    key = _loopback_key(requested)
    return key is not None and any(_loopback_key(uri) == key for uri in listed)


def cache_ttl_seconds(cache_control: str | None) -> int:
    if not cache_control:
        return CIMD_CACHE_DEFAULT_TTL_SECONDS
    lowered = cache_control.lower()
    if "no-store" in lowered or "no-cache" in lowered:
        return CIMD_CACHE_MIN_TTL_SECONDS
    match = _MAX_AGE.search(cache_control)
    if match is None:
        return CIMD_CACHE_DEFAULT_TTL_SECONDS
    return max(CIMD_CACHE_MIN_TTL_SECONDS, min(int(match.group(1)), CIMD_CACHE_MAX_TTL_SECONDS))


@dataclass
class _CacheEntry:
    client: CimdClient
    fresh_until: float
    stale_until: float


_cache: OrderedDict[str, _CacheEntry] = OrderedDict()
_negative: OrderedDict[str, float] = OrderedDict()
_inflight: dict[str, asyncio.Future] = {}
_fetch_slots = asyncio.Semaphore(CIMD_MAX_CONCURRENT_FETCHES)


def clear_cache() -> None:
    _cache.clear()
    _negative.clear()


def cache_size() -> int:
    return len(_cache)


def _evict(store: OrderedDict) -> None:
    while len(store) > CIMD_CACHE_MAX_ENTRIES:
        store.popitem(last=False)


def _cache_fresh(client_id: str) -> CimdClient | None:
    entry = _cache.get(client_id)
    if entry is None or entry.fresh_until <= _now():
        return None
    _cache.move_to_end(client_id)
    return entry.client


def _cache_stale(client_id: str) -> CimdClient | None:
    entry = _cache.get(client_id)
    if entry is None:
        return None
    if entry.stale_until <= _now():
        del _cache[client_id]
        return None
    entry.fresh_until = _now() + CIMD_CACHE_MIN_TTL_SECONDS
    _cache.move_to_end(client_id)
    return entry.client


def _cache_put(client_id: str, client: CimdClient, ttl_seconds: int) -> None:
    now = _now()
    _cache[client_id] = _CacheEntry(client, now + ttl_seconds, now + ttl_seconds + CIMD_STALE_MAX_SECONDS)
    _cache.move_to_end(client_id)
    _evict(_cache)


def _recently_failed(client_id: str) -> bool:
    until = _negative.get(client_id)
    if until is None:
        return False
    if until <= _now():
        del _negative[client_id]
        return False
    return True


async def _fetch_validated(client_id: str) -> tuple[CimdClient, int]:
    parts = validate_client_id_url(client_id)
    try:
        async with asyncio.timeout(CIMD_FETCH_TIMEOUT_SECONDS):
            address = await resolve_public_address(parts.hostname or "", parts.port or 443)
            fetched = await fetch_document(client_id, parts, address)
    except (TimeoutError, httpcore.TimeoutException):
        raise CimdTransientError("client metadata URL timed out") from None
    except (httpcore.NetworkError, httpcore.ProtocolError, OSError):
        raise CimdTransientError("client metadata URL could not be fetched") from None
    return parse_client_document(client_id, fetched.body), cache_ttl_seconds(fetched.cache_control)


def _remember_failure(client_id: str, exc: CimdError) -> None:
    logger.warning("CIMD client resolution failed client=%s reason=%s", _loggable(client_id), sanitize(str(exc)))
    _negative[client_id] = _now() + CIMD_NEGATIVE_TTL_SECONDS
    _negative.move_to_end(client_id)
    _evict(_negative)


async def _load(client_id: str) -> CimdClient:
    if _fetch_slots.locked():
        raise CimdError("too many client metadata lookups in progress")
    async with _fetch_slots:
        try:
            client, ttl = await _fetch_validated(client_id)
        except CimdTransientError as exc:
            stale = _cache_stale(client_id)
            if stale is not None:
                logger.warning("CIMD refetch failed, serving stale metadata client=%s", _loggable(client_id))
                return stale
            _remember_failure(client_id, exc)
            raise
        except CimdError as exc:
            _remember_failure(client_id, exc)
            raise
    _cache_put(client_id, client, ttl)
    _negative.pop(client_id, None)
    logger.info("CIMD client metadata fetched client=%s", _loggable(client_id))
    return client


async def _load_once(client_id: str) -> CimdClient:
    flight = _inflight.get(client_id)
    if flight is None:
        flight = asyncio.ensure_future(_load(client_id))
        _inflight[client_id] = flight

        def _finished(done: asyncio.Future) -> None:
            _inflight.pop(client_id, None)
            if not done.cancelled():
                done.exception()

        flight.add_done_callback(_finished)
    return await asyncio.shield(flight)


async def resolve_cimd_client(client_id: str):
    from giljo_mcp.services.oauth_service import ResolvedClient

    client = _cache_fresh(client_id)
    if client is None:
        if _recently_failed(client_id):
            raise CimdError("client metadata URL failed recently")
        client = await _load_once(client_id)
    return ResolvedClient(
        client_id=client.client_id,
        client_name=client.client_name,
        redirect_uris=list(client.redirect_uris),
        client_secret_hash=None,
        redirect_matcher=partial(redirect_uri_matches, list(client.redirect_uris)),
    )
