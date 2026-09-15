# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import datetime
import ipaddress

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException

from api.endpoints import configuration_ssl as cfg


def _write_self_signed_pair(tmp_path) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test.local")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(2040, 1, 1, tzinfo=datetime.UTC))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


class TestValidateCertPair:

    def test_valid_self_signed_pair_accepted(self, tmp_path):
        cert_path, key_path = _write_self_signed_pair(tmp_path)
        cfg._validate_cert_pair(cert_path, key_path)

    def test_missing_file_rejected(self, tmp_path):
        cert_path, _key_path = _write_self_signed_pair(tmp_path)
        with pytest.raises(HTTPException) as exc:
            cfg._validate_cert_pair(cert_path, str(tmp_path / "nope.pem"))
        assert exc.value.status_code == 400

    def test_mismatched_pair_rejected(self, tmp_path):
        cert_path, _ = _write_self_signed_pair(tmp_path)
        other = tmp_path / "other"
        other.mkdir()
        _, foreign_key = _write_self_signed_pair(other)
        with pytest.raises(HTTPException) as exc:
            cfg._validate_cert_pair(cert_path, foreign_key)
        assert exc.value.status_code == 400

    def test_garbage_pem_rejected(self, tmp_path):
        bad_cert = tmp_path / "bad_cert.pem"
        bad_key = tmp_path / "bad_key.pem"
        bad_cert.write_text("not a certificate")
        bad_key.write_text("not a key")
        with pytest.raises(HTTPException) as exc:
            cfg._validate_cert_pair(str(bad_cert), str(bad_key))
        assert exc.value.status_code == 400


class TestToggleRequiresProvisionedCert:

    @pytest.mark.asyncio
    async def test_enable_without_cert_rejected_no_mint(self, monkeypatch):
        monkeypatch.setattr(cfg, "_ssl_status_from_config", lambda: (False, None, None, False))

        def _boom(_config):
            raise AssertionError("toggle must NOT write config.yaml when rejecting a no-cert enable")

        import giljo_mcp._config_io as cio

        monkeypatch.setattr(cio, "write_config", _boom)

        with pytest.raises(HTTPException) as exc:
            await cfg.toggle_ssl(cfg.SSLToggleRequest(enabled=True), current_user=None, _ce=None)
        assert exc.value.status_code == 400
        assert "does not mint" in exc.value.detail.lower() or "no certificate" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_disable_always_allowed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "_ssl_status_from_config", lambda: (True, None, None, False))
        captured = {}

        def _fake_read():
            return {"features": {"ssl_enabled": True}}

        def _fake_write(config):
            captured.update(config)

        import giljo_mcp._config_io as cio

        monkeypatch.setattr(cio, "read_config", _fake_read)
        monkeypatch.setattr(cio, "write_config", _fake_write)

        result = await cfg.toggle_ssl(cfg.SSLToggleRequest(enabled=False), current_user=None, _ce=None)
        assert result.ssl_enabled is False
        assert result.restart_required is True
        assert captured["features"]["ssl_enabled"] is False
