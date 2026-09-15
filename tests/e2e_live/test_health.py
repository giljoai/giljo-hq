# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


@pytest.mark.network
def test_health_endpoint_ok(http_client):
    resp = http_client.get("/health")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body.get("status") in {"healthy", "degraded"}, body
    assert isinstance(body.get("checks"), dict), body
