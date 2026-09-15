# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime

import bcrypt


_API_KEY_HASH_PREFIX = "sha256$"
_BCRYPT_PREFIXES = ("$2b$", "$2a$", "$2y$")


def generate_api_key() -> str:
    random_part = secrets.token_urlsafe(32)
    return f"gk_{random_part}"


def hash_api_key(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"{_API_KEY_HASH_PREFIX}{digest}"


def verify_api_key(api_key: str, key_hash: str) -> bool:
    if not key_hash:
        return False
    if key_hash.startswith(_API_KEY_HASH_PREFIX):
        expected = key_hash[len(_API_KEY_HASH_PREFIX) :]
        actual = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, expected)
    if key_hash.startswith(_BCRYPT_PREFIXES):
        try:
            return bcrypt.checkpw(api_key.encode("utf-8"), key_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    return False



_VERIFY_CACHE_TTL_POSITIVE = 60.0
_VERIFY_CACHE_TTL_NEGATIVE = 5.0
_VERIFY_CACHE_MAX_ENTRIES = 4096

_verify_cache: dict[str, tuple[bool, float]] = {}


def _verify_cache_key(key_id: str, api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"{key_id}:{digest}"


def _verify_cache_get(cache_key: str) -> bool | None:
    entry = _verify_cache.get(cache_key)
    if entry is None:
        return None
    verdict, expires_at = entry
    if time.monotonic() >= expires_at:
        _verify_cache.pop(cache_key, None)
        return None
    return verdict


def _verify_cache_put(
    cache_key: str,
    *,
    verdict: bool,
    expires_at: datetime | None,
) -> None:
    if len(_verify_cache) >= _VERIFY_CACHE_MAX_ENTRIES:
        try:
            oldest = next(iter(_verify_cache))
            _verify_cache.pop(oldest, None)
        except StopIteration:
            pass
    ttl = _VERIFY_CACHE_TTL_POSITIVE if verdict else _VERIFY_CACHE_TTL_NEGATIVE
    deadline = time.monotonic() + ttl
    if expires_at is not None:
        seconds_to_expiry = (expires_at - datetime.now(UTC)).total_seconds()
        if seconds_to_expiry <= 0:
            return
        deadline = min(deadline, time.monotonic() + seconds_to_expiry)
    _verify_cache[cache_key] = (verdict, deadline)


async def verify_api_key_cached(
    api_key: str,
    key_hash: str,
    *,
    key_id: str,
    expires_at: datetime | None,
) -> bool:
    cache_key = _verify_cache_key(key_id, api_key)
    cached = _verify_cache_get(cache_key)
    if cached is not None:
        return cached

    verdict = await asyncio.to_thread(verify_api_key, api_key, key_hash)
    _verify_cache_put(cache_key, verdict=verdict, expires_at=expires_at)
    return verdict


def bust_api_key_cache(key_id: str) -> None:
    prefix = f"{key_id}:"
    stale = [k for k in _verify_cache if k.startswith(prefix)]
    for k in stale:
        _verify_cache.pop(k, None)


def clear_api_key_verify_cache() -> None:
    _verify_cache.clear()


def get_key_prefix(api_key: str, length: int = 12) -> str:
    if len(api_key) <= length:
        return api_key
    return f"{api_key[:length]}..."
