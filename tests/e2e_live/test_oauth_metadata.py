# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest


@pytest.mark.network
def test_oauth_protected_resource_metadata_shape(http_client):
    resp = http_client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-type", "").startswith("application/json"), resp.headers.get("content-type")

    body = resp.json()
    assert isinstance(body.get("resource"), str) and body["resource"], body
    assert isinstance(body.get("authorization_servers"), list) and body["authorization_servers"], body
    assert isinstance(body.get("scopes_supported"), list), body
    assert isinstance(body.get("bearer_methods_supported"), list), body
    assert body.get("resource_indicators_supported") is True, body
