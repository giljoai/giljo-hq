# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import socket
import ssl
import time

import pytest


@pytest.mark.network
def test_tls_handshake_and_cert_valid(target):
    if target.scheme != "https":
        pytest.skip(reason="target is not https; TLS cert check not applicable")

    ctx = ssl.create_default_context()
    with socket.create_connection((target.host, target.port), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=target.host) as ssock:
            cert = ssock.getpeercert()

    assert cert, "no peer certificate returned by the server"
    not_after = ssl.cert_time_to_seconds(cert["notAfter"])
    assert not_after > time.time(), f"certificate already expired at {cert['notAfter']}"
