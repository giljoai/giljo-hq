# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from fastapi.responses import FileResponse

from api.endpoints import configuration as cfg




def _write_self_signed_pair(tmp_path: Path) -> tuple[str, str]:
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
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
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




class TestDownloadRootCa:

    @pytest.mark.asyncio
    async def test_serves_configured_cert_as_file_response(self, monkeypatch, tmp_path):
        cert_path, key_path = _write_self_signed_pair(tmp_path)

        import api.endpoints.configuration_ssl as ssl_mod

        monkeypatch.setattr(
            ssl_mod,
            "_ssl_status_from_config",
            lambda: (True, cert_path, key_path, True),
        )

        response = await cfg.download_root_ca()

        assert isinstance(response, FileResponse), "Expected a FileResponse when cert is configured"
        assert response.path == cert_path, "FileResponse must point at the configured cert path"
        assert response.filename == "giljo-server-cert.pem", (
            "Canonical downloaded filename must be giljo-server-cert.pem (Global Decision 1)"
        )

    @pytest.mark.asyncio
    async def test_404_when_no_cert_configured(self, monkeypatch):
        import api.endpoints.configuration_ssl as ssl_mod

        monkeypatch.setattr(
            ssl_mod,
            "_ssl_status_from_config",
            lambda: (False, None, None, False),
        )

        with pytest.raises(HTTPException) as exc:
            await cfg.download_root_ca()

        assert exc.value.status_code == 404, "Expected 404 when no cert is configured (has_cert=False)"

    @pytest.mark.asyncio
    async def test_404_when_https_disabled_and_no_cert(self, monkeypatch):
        import api.endpoints.configuration_ssl as ssl_mod

        monkeypatch.setattr(
            ssl_mod,
            "_ssl_status_from_config",
            lambda: (True, None, None, False),
        )

        with pytest.raises(HTTPException) as exc:
            await cfg.download_root_ca()

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cert_served_even_when_ssl_disabled(self, monkeypatch, tmp_path):
        cert_path, key_path = _write_self_signed_pair(tmp_path)

        import api.endpoints.configuration_ssl as ssl_mod

        monkeypatch.setattr(
            ssl_mod,
            "_ssl_status_from_config",
            lambda: (False, cert_path, key_path, True),
        )

        response = await cfg.download_root_ca()

        assert isinstance(response, FileResponse)
        assert response.path == cert_path
        assert response.filename == "giljo-server-cert.pem"

    @pytest.mark.asyncio
    async def test_response_media_type_is_pem(self, monkeypatch, tmp_path):
        cert_path, key_path = _write_self_signed_pair(tmp_path)

        import api.endpoints.configuration_ssl as ssl_mod

        monkeypatch.setattr(
            ssl_mod,
            "_ssl_status_from_config",
            lambda: (True, cert_path, key_path, True),
        )

        response = await cfg.download_root_ca()

        assert response.media_type == "application/x-pem-file", (
            "FileResponse must use application/x-pem-file so browsers prompt a download"
        )
