# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

from api.wiring.openapi import build_openapi_servers


def test_servers_is_single_root_relative_entry():
    assert build_openapi_servers() == [{"url": "/", "description": "This server"}]


def test_never_advertises_bind_address_or_hardcoded_host():
    blob = repr(build_openapi_servers())
    assert "0.0.0.0" not in blob
    assert "localhost" not in blob
    assert "127.0.0.1" not in blob
    assert "7272" not in blob


def test_every_entry_has_fastapi_required_shape():
    servers = build_openapi_servers()
    assert servers, "servers list must be non-empty"
    for entry in servers:
        assert set(entry) >= {"url", "description"}
        assert entry["url"].startswith("/")
