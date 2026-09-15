# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


@pytest.mark.network
def test_static_security_headers_present(http_client):
    h = http_client.get("/health").headers
    assert h.get("X-Content-Type-Options") == "nosniff", dict(h)
    assert h.get("X-Frame-Options") == "DENY", dict(h)
    assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin", dict(h)

    csp = h.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp, csp
    assert "frame-ancestors 'none'" in csp, csp

    assert "geolocation=()" in h.get("Permissions-Policy", ""), h.get("Permissions-Policy")


@pytest.mark.network
def test_hsts_present_on_https(http_client, target):
    if target.scheme != "https":
        pytest.skip(reason="HSTS is only emitted over https")

    hsts = http_client.get("/health").headers.get("Strict-Transport-Security", "")
    assert "max-age=" in hsts, f"HSTS missing/empty: {hsts!r}"
    assert "includeSubDomains" in hsts, hsts
