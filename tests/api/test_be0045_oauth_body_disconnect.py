# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

import pytest


_PARTIAL_BODIES = {
    "application/x-www-form-urlencoded": b"grant_type=authorization_code&code=abc",
    "application/json": b'{"grant_type": "authorization_code", "code": "ab',
}


async def _post_then_hang_up(app, path: str, content_type: str) -> list[dict]:
    partial = _PARTIAL_BODIES[content_type]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"test"),
            (b"content-type", content_type.encode()),
            (b"content-length", str(len(partial) + 500).encode()),
        ],
        "client": ("127.0.0.1", 50045),
        "server": ("test", 80),
    }
    pending = [{"type": "http.request", "body": partial, "more_body": True}]
    sent: list[dict] = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/oauth/token", "/api/oauth/refresh"])
@pytest.mark.parametrize("content_type", list(_PARTIAL_BODIES))
async def test_hang_up_mid_body_is_not_a_server_error(api_client, caplog, monkeypatch, path, content_type):
    from api.app import app
    from api.endpoints import oauth as oauth_endpoints

    issued: list[str] = []

    async def _no_refresh(*args, **kwargs):
        issued.append("refresh")
        raise AssertionError("refresh grant reached on an incomplete body")

    monkeypatch.setattr(oauth_endpoints, "_refresh_token_grant_response", _no_refresh)

    with caplog.at_level(logging.INFO):
        sent = await _post_then_hang_up(app, path, content_type)

    unexpected = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not unexpected, [r.getMessage() for r in unexpected]
    assert issued == []

    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) <= 1
    if starts:
        assert starts[0]["status"] == 400
    assert any("disconnected" in r.getMessage() for r in caplog.records if r.name == "api.endpoints.oauth")
