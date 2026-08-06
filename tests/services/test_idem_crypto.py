# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Unit tests for ``giljo_mcp.services._idem_crypto`` (SEC-9227f, M2a).

Direct tests of the shared idempotency-cache encryption primitive: wire
format, nonce freshness, lazy key derivation, and the fail-secure decrypt
contract (every failure is ``None``, never an exception). The end-to-end
behavior through the /token and /refresh cache paths is covered by
``tests/services/test_sec9227f_idem_cache_encryption.py``.

Parallel-safe: per-test derived-key reset via the autouse fixture; secrets
set only through ``monkeypatch``; no module-level mutable state.
"""

from __future__ import annotations

import base64

import pytest

from giljo_mcp.services import _idem_crypto


@pytest.fixture(autouse=True)
def _isolated_key_cache():
    """Fresh derived-key cache per test so a key derived under one test's JWT
    secret cannot leak into the next (the derivation is once-per-process)."""
    _idem_crypto.reset_key_cache_for_tests()
    yield
    _idem_crypto.reset_key_cache_for_tests()


class TestWireFormat:
    def test_version_prefix_and_round_trip(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        token = _idem_crypto.encrypt_payload("payload text")
        assert token.startswith("v1:")
        assert _idem_crypto.decrypt_payload(token) == "payload text"

    def test_fresh_nonce_per_entry(self, monkeypatch):
        """Identical plaintexts must encrypt to different ciphertexts (random
        12-byte nonce per entry) — and both must still decrypt."""
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        one = _idem_crypto.encrypt_payload("same plaintext")
        two = _idem_crypto.encrypt_payload("same plaintext")
        assert one != two
        assert _idem_crypto.decrypt_payload(one) == "same plaintext"
        assert _idem_crypto.decrypt_payload(two) == "same plaintext"

    def test_ciphertext_reveals_no_plaintext(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        secret_text = "raw-token-value-must-not-appear"
        token = _idem_crypto.encrypt_payload(secret_text)
        assert secret_text not in token


class TestFailSecureDecrypt:
    """Every decrypt failure returns None with a warning — never an exception."""

    def test_tampered_ciphertext_is_none(self, monkeypatch, caplog):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        token = _idem_crypto.encrypt_payload("payload")
        body = bytearray(base64.b64decode(token[3:]))
        body[-1] ^= 0x01
        tampered = "v1:" + base64.b64encode(bytes(body)).decode("ascii")

        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="giljo_mcp.services._idem_crypto"):
            assert _idem_crypto.decrypt_payload(tampered) is None
        assert any("oauth_idem_cache_decrypt_failed" in r.message for r in caplog.records)

    def test_wrong_key_is_none(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "secret-key-A")
        token = _idem_crypto.encrypt_payload("payload")
        _idem_crypto.reset_key_cache_for_tests()
        monkeypatch.setenv("JWT_SECRET", "secret-key-B")
        assert _idem_crypto.decrypt_payload(token) is None

    @pytest.mark.parametrize(
        "value",
        [
            '{"response_body": {}}',  # legacy unencrypted entry
            "v2:AAAA",  # unknown future version
            "v1:!!!not-base64!!!",  # malformed base64
            "v1:",  # empty body
            "v1:QUJD",  # too short to hold a nonce
            "",  # empty string
        ],
    )
    def test_malformed_values_are_none(self, monkeypatch, value):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        assert _idem_crypto.decrypt_payload(value) is None


class TestLazyKeyDerivation:
    def test_key_is_not_derived_at_import_time(self, monkeypatch):
        """Importing the module (already imported here) must not have required
        a JWT secret; only encrypt use derives it. With no secret configured,
        encryption raises the same RuntimeError token-signing would — and the
        read path still degrades to a miss."""
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("GILJO_MCP_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError):
            _idem_crypto.encrypt_payload("x")
        assert _idem_crypto.decrypt_payload("v1:QUJD") is None

    def test_derived_key_is_cached_per_process(self, monkeypatch):
        """A secret change WITHOUT a reset does not re-derive (once-per-process
        cache); after reset the new secret takes effect."""
        monkeypatch.setenv("JWT_SECRET", "secret-key-A")
        token = _idem_crypto.encrypt_payload("payload")
        monkeypatch.setenv("JWT_SECRET", "secret-key-B")
        # No reset: still the cached key-A, so decryption succeeds.
        assert _idem_crypto.decrypt_payload(token) == "payload"
        _idem_crypto.reset_key_cache_for_tests()
        # After reset: derived under key-B, so the key-A token is a miss.
        assert _idem_crypto.decrypt_payload(token) is None
