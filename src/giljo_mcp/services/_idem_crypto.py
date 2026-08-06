# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Authenticated encryption for OAuth idempotency-cache payloads (SEC-9227f, M2a).

The /token and /refresh idempotency windows must cache the FULL response body
(the whole point is re-serving the SAME token pair to a concurrent honest
retry), but the serialized JSON contains the raw access-token JWT and the raw
refresh token. Storing that readable contradicts the codebase's own contract
("the raw value is returned to the client ONCE in the response and never
persisted" — ``oauth_refresh_service.hash_refresh_token``): on SaaS the blob
transits to and sits in Redis for the window, where persistence (RDB/AOF),
MONITOR access, or a Redis compromise exposes live token pairs.

This module is the ONE shared implementation both cache paths import — the
serialize/deserialize choke-point helpers in ``oauth_token_idempotency`` and
``oauth_refresh_service`` wrap :func:`encrypt_payload` after serializing and
:func:`decrypt_payload` before deserializing. Nothing else writes to or reads
from the ``oauth_idempotency`` / ``oauth_refresh`` backends.

Design (SEC-9227f):

* Cipher: AES-256-GCM (authenticated encryption — tampering is detected, not
  just garbled). Fresh random 12-byte nonce per entry, prepended to the
  ciphertext. Nonce reuse is not a practical concern at one random nonce per
  cache write within a seconds-long TTL window.
* Key: derived from the existing JWT signing secret via HKDF-SHA256 with a
  dedicated info label, so no new key-management surface exists. The JWT
  secret already has full entropy and is already the server's root secret —
  an attacker who has it can mint tokens outright, so deriving from it adds
  no new exposure. Secret resolution stays behind the documented seam
  ``JWTManager.get_secret_key()`` (one place resolves env precedence).
* Laziness: the key is derived at FIRST USE and cached per process — never at
  import. The JWT secret may not be resolvable at import time in some test
  bootstraps; this mirrors how ``JWTManager`` defers ``_get_secret_key()`` to
  call time.
* Format: ``"v1:" + base64(nonce || ciphertext)``. The version prefix lets a
  future rotation/format change dual-read old entries.
* Fail-secure degradation: ANY decrypt failure — tampered entry, wrong key
  (rotated mid-window), malformed prefix, stale format — is a cache MISS
  (``None`` + one warning log), NEVER an exception. A broken cache entry must
  not break a token exchange; the caller falls through to normal processing.
"""

from __future__ import annotations

import base64
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from giljo_mcp.auth.jwt_manager import JWTManager


logger = logging.getLogger(__name__)

_FORMAT_PREFIX = "v1:"
_NONCE_BYTES = 12
_KEY_INFO_LABEL = b"oauth-idem-cache-v1"

# Per-process lazily derived key. The JWT secret is stable for the process
# lifetime, so one derivation suffices; a mid-window secret rotation on a
# restart simply makes old entries undecryptable, which degrades to a cache
# miss below (the fail-secure contract).
_derived_key: bytes | None = None


def _get_key() -> bytes:
    """Return the AES-256 cache key, deriving it from the JWT secret on first use.

    HKDF-SHA256 with a dedicated info label: the cache key is cryptographically
    independent of the JWT signing key even though both derive from the same
    root secret, so token-signing and cache-encryption never share key material
    directly. Raises ``RuntimeError`` if no JWT secret is configured — the same
    condition under which the grant itself could not have signed a JWT.
    """
    global _derived_key  # noqa: PLW0603 — deliberate once-per-process key cache
    if _derived_key is None:
        secret = JWTManager.get_secret_key().encode("utf-8")
        _derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_KEY_INFO_LABEL,
        ).derive(secret)
    return _derived_key


def encrypt_payload(plaintext: str) -> str:
    """Encrypt a serialized cache payload to the ``v1:`` opaque wire format."""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_get_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _FORMAT_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_payload(value: str) -> str | None:
    """Decrypt a stored cache value back to the serialized payload.

    Returns ``None`` — a cache miss — on ANY failure: unknown/missing format
    prefix, malformed base64, truncated blob, authentication-tag mismatch
    (tampering or a different key). One warning is logged; no exception ever
    reaches the caller (fail-secure contract, see module docstring).
    """
    if not value.startswith(_FORMAT_PREFIX):
        logger.warning("oauth_idem_cache_decrypt_failed reason=unknown_format_prefix")
        return None
    try:
        blob = base64.b64decode(value[len(_FORMAT_PREFIX) :], validate=True)
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return AESGCM(_get_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (ValueError, InvalidTag):
        # ValueError covers bad base64 (binascii.Error subclass) and a blob too
        # short to hold a nonce; InvalidTag is tampering or a rotated key.
        logger.warning("oauth_idem_cache_decrypt_failed reason=undecryptable_entry")
        return None
    except RuntimeError:
        # No JWT secret configured (JWTManager raises RuntimeError). The grant
        # will fail loudly at token-signing time anyway; the cache read itself
        # must still degrade to a miss, never a 500.
        logger.warning("oauth_idem_cache_decrypt_failed reason=jwt_secret_unavailable")
        return None


def reset_key_cache_for_tests() -> None:
    """Test-only escape hatch: drop the per-process derived key.

    Production code MUST NOT call this. Tests that vary the JWT secret use it
    so a key derived under one secret cannot leak into the next test
    (xdist-safety: the derivation is otherwise once-per-process).
    """
    global _derived_key  # noqa: PLW0603 — test-only reset of the key cache
    _derived_key = None
