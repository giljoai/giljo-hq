# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

_derived_key: bytes | None = None


def _get_key() -> bytes:
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
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_get_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _FORMAT_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_payload(value: str) -> str | None:
    if not value.startswith(_FORMAT_PREFIX):
        logger.warning("oauth_idem_cache_decrypt_failed reason=unknown_format_prefix")
        return None
    try:
        blob = base64.b64decode(value[len(_FORMAT_PREFIX) :], validate=True)
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return AESGCM(_get_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (ValueError, InvalidTag):
        logger.warning("oauth_idem_cache_decrypt_failed reason=undecryptable_entry")
        return None
    except RuntimeError:
        logger.warning("oauth_idem_cache_decrypt_failed reason=jwt_secret_unavailable")
        return None


def reset_key_cache_for_tests() -> None:
    global _derived_key  # noqa: PLW0603 — test-only reset of the key cache
    _derived_key = None
