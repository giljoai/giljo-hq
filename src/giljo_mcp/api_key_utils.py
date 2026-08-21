# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
API Key utilities for hashing, validation, and generation.

This module provides utilities for secure API key management in LAN/WAN modes:
- Generate cryptographically secure API keys with gk_ prefix
- Hash API keys using bcrypt for secure storage
- Verify API keys against stored hashes
- Extract display prefixes for UI purposes

Security Notes (BE-6060b):
- NEW API keys are stored as a format-prefixed fast hash ``sha256$<hex>``.
  ``gk_`` keys are 256-bit machine tokens, so the slow-hash rationale that
  protects low-entropy passwords does not apply; the GitHub/Stripe pattern of a
  fast deterministic hash is correct here and drops auth from ~300ms blocking
  bcrypt to ~1ms. Passwords are unaffected and stay bcrypt.
- LEGACY keys remain bcrypt (``$2b$``); ``verify_api_key`` format-detects both,
  so the two coexist and converge as users rotate keys (no migration, existing
  rows are NEVER rewritten).
- Original keys are NEVER stored in plaintext.
- Keys are only shown once at generation time.
- Display prefixes show first 12 characters for user reference.

Usage Example:
    from giljo_mcp.api_key_utils import generate_api_key, hash_api_key, verify_api_key

    # Generate new key
    api_key = generate_api_key()  # Returns: "gk_abc123..."

    # Hash for storage (sha256$<hex> for new keys)
    key_hash = hash_api_key(api_key)

    # Later, verify incoming key (accepts sha256$ AND legacy $2b$ hashes)
    if verify_api_key(api_key, key_hash):
        # Valid key
        pass
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime

import bcrypt


# BE-6060b: API-key hash formats. New keys are stored as a fast, deterministic
# sha256 digest (high-entropy machine tokens don't need a slow password hash);
# legacy keys remain bcrypt and keep verifying. verify_api_key() format-detects
# on these prefixes. NEVER rewrite existing rows — the two formats coexist.
_API_KEY_HASH_PREFIX = "sha256$"
_BCRYPT_PREFIXES = ("$2b$", "$2a$", "$2y$")


def generate_api_key() -> str:
    """
    Generate a new cryptographically secure API key.

    The key format is: gk_<32-byte-urlsafe-token>
    - gk_ prefix identifies it as a GiljoAI key
    - 32-byte token provides ~256 bits of entropy
    - URL-safe encoding (no special chars that need escaping)

    Returns:
        API key string (e.g., "gk_xyzABC123...")

    Example:
        >>> api_key = generate_api_key()
        >>> api_key.startswith("gk_")
        True
        >>> len(api_key) > 40  # gk_ (3) + token (~43 chars)
        True
    """
    random_part = secrets.token_urlsafe(32)
    return f"gk_{random_part}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for storage as a format-prefixed fast hash (BE-6060b).

    API keys are high-entropy machine tokens (``gk_`` + ``secrets.token_urlsafe(32)``
    = 256 bits), so the slow-hash rationale that protects low-entropy passwords does
    not apply. New keys are stored as ``sha256$<hex>`` (the GitHub/Stripe pattern):
    a fast, deterministic, salt-free digest. This drops auth from a ~250-400ms
    blocking bcrypt to a ~microsecond compare, removes bcrypt's silent 72-byte
    truncation, and makes the unique index on ``key_hash`` a real collision guard.

    NEVER used for passwords — passwords stay bcrypt (``utils.password_helper``).
    Existing ``$2b$`` key rows are NEVER rewritten; :func:`verify_api_key` format-
    detects both, so the formats coexist and converge as users rotate keys.

    Args:
        api_key: The plaintext API key to hash

    Returns:
        A ``sha256$<64-hex>`` string (71 chars; fits the ``String(255)`` column)

    Example:
        >>> api_key = "gk_abc123"
        >>> key_hash = hash_api_key(api_key)
        >>> key_hash.startswith("sha256$")
        True
        >>> len(key_hash)
        71
    """
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"{_API_KEY_HASH_PREFIX}{digest}"


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """
    Verify an API key against a stored hash, format-detecting the algorithm.

    Supports both storage formats so a rotation- or downgrade-era mix of rows all
    verify (BE-6060b):

    * ``sha256$<hex>`` (new) — recompute the digest and ``hmac.compare_digest``
      (constant-time) against the stored hex.
    * ``$2b$`` / ``$2a$`` / ``$2y$`` (legacy) — ``bcrypt.checkpw`` (constant-time).

    Any other / malformed value fails CLOSED (returns ``False``) and NEVER raises,
    so an unexpected stored shape can never leak an exception out of the auth
    boundary.

    Args:
        api_key: The plaintext API key to verify
        key_hash: The stored hash (either format)

    Returns:
        True if key matches hash, False otherwise

    Example:
        >>> api_key = generate_api_key()
        >>> key_hash = hash_api_key(api_key)
        >>> verify_api_key(api_key, key_hash)
        True
        >>> verify_api_key("gk_wrong", key_hash)
        False
    """
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
            # Malformed bcrypt hash (e.g. a sha256-format hash reaching a
            # downgraded reader) — fail closed, never raise. See BE-6060b.
            return False
    return False


# ---------------------------------------------------------------------------
# BE-6060a: async cached verify — keep bcrypt OFF the event loop.
#
# verify_api_key() runs a synchronous bcrypt.checkpw (~250-400ms). On the MCP
# transport hot path (api-key-as-bearer) this blocked the single hosted worker
# and was re-run on every poll. verify_api_key_cached() moves the bcrypt call to
# a worker thread (asyncio.to_thread) and memoizes the verdict in a short-lived
# in-process TTL cache, mirroring oauth_revocation_service.py's pattern.
#
# Cache key = "{key_id}:{sha256(presented_secret)}". The sha256 keeps the
# plaintext secret out of the cache; the key_id prefix lets a revoke/deactivate
# bust every verdict for that key (bust_api_key_cache) while verdicts stay
# secret-specific (a wrong secret presented against the same key_id caches a
# separate negative verdict and cannot ride a different secret's positive one).
# ---------------------------------------------------------------------------

# Positive verdicts (secret matches hash) are stable for the key's lifetime, so
# a 60s TTL is safe. Negative verdicts live a much shorter window so a corrected
# secret surfaces quickly. NEVER cache past the key's expires_at.
_VERIFY_CACHE_TTL_POSITIVE = 60.0
_VERIFY_CACHE_TTL_NEGATIVE = 5.0
_VERIFY_CACHE_MAX_ENTRIES = 4096

# Cache: "{key_id}:{sha256(secret)}" -> (verdict: bool, expires_at_monotonic: float)
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
        # Cheap FIFO-ish eviction: drop the oldest insertion (mirrors
        # oauth_revocation_service._cache_put).
        try:
            oldest = next(iter(_verify_cache))
            _verify_cache.pop(oldest, None)
        except StopIteration:
            pass
    ttl = _VERIFY_CACHE_TTL_POSITIVE if verdict else _VERIFY_CACHE_TTL_NEGATIVE
    deadline = time.monotonic() + ttl
    # Never cache a positive verdict past the key's own expiry.
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
    """Verify an API key off the event loop, with a short-lived verdict cache.

    On a cache miss the bcrypt comparison runs via ``asyncio.to_thread`` so it
    never blocks the loop, then the boolean verdict is memoized. The cache key
    incorporates ``sha256(api_key)`` (never plaintext) and ``key_id`` so a
    revoke can bust every verdict for the key via :func:`bust_api_key_cache`.

    Args:
        api_key: The plaintext API key presented by the client.
        key_hash: The stored bcrypt hash for ``key_id``.
        key_id: The API key row id (``api_keys.id``). Scopes + busts the cache.
        expires_at: The key's expiry (or ``None``). A verdict is never cached
            past this instant.

    Returns:
        True if the key matches the hash, False otherwise.
    """
    cache_key = _verify_cache_key(key_id, api_key)
    cached = _verify_cache_get(cache_key)
    if cached is not None:
        return cached

    verdict = await asyncio.to_thread(verify_api_key, api_key, key_hash)
    _verify_cache_put(cache_key, verdict=verdict, expires_at=expires_at)
    return verdict


def bust_api_key_cache(key_id: str) -> None:
    """Evict every cached verdict for ``key_id``.

    Called from the API-key revoke/deactivate path so revocation stays
    near-instant — a deactivated key must not keep authenticating off a stale
    positive verdict for the rest of the TTL window.
    """
    prefix = f"{key_id}:"
    stale = [k for k in _verify_cache if k.startswith(prefix)]
    for k in stale:
        _verify_cache.pop(k, None)


def clear_api_key_verify_cache() -> None:
    """Test helper: wipe the entire in-process verify cache."""
    _verify_cache.clear()


def get_key_prefix(api_key: str, length: int = 12) -> str:
    """
    Get display-friendly prefix of an API key.

    Shows only the first N characters followed by ellipsis.
    Safe to display in logs, UI, etc.

    Args:
        api_key: The full API key
        length: Number of characters to include (default: 12)

    Returns:
        Display string (e.g., "gk_abc12345...")

    Example:
        >>> api_key = "gk_verylongtoken123456789"
        >>> get_key_prefix(api_key)
        'gk_verylongt...'
        >>> get_key_prefix(api_key, 8)
        'gk_veryl...'
    """
    if len(api_key) <= length:
        return api_key
    return f"{api_key[:length]}..."
