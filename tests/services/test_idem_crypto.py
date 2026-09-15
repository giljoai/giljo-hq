# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import base64

import pytest

from giljo_mcp.services import _idem_crypto


@pytest.fixture(autouse=True)
def _isolated_key_cache():
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
            '{"response_body": {}}',
            "v2:AAAA",
            "v1:!!!not-base64!!!",
            "v1:",
            "v1:QUJD",
            "",
        ],
    )
    def test_malformed_values_are_none(self, monkeypatch, value):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        assert _idem_crypto.decrypt_payload(value) is None


class TestLazyKeyDerivation:
    def test_key_is_not_derived_at_import_time(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("GILJO_MCP_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError):
            _idem_crypto.encrypt_payload("x")
        assert _idem_crypto.decrypt_payload("v1:QUJD") is None

    def test_derived_key_is_cached_per_process(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "secret-key-A")
        token = _idem_crypto.encrypt_payload("payload")
        monkeypatch.setenv("JWT_SECRET", "secret-key-B")
        assert _idem_crypto.decrypt_payload(token) == "payload"
        _idem_crypto.reset_key_cache_for_tests()
        assert _idem_crypto.decrypt_payload(token) is None
