# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from starlette.requests import Request


_SESSION_TENANT = "tk_be9703c_a19"


@pytest.mark.asyncio
async def test_session_check_without_a_database_answers_503(monkeypatch):
    from api.app_state import state
    from api.endpoints.mcp_auth_middleware import MCPAuthMiddleware

    monkeypatch.setattr(state, "db_manager", None)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"mcp-session-id", b"a" * 32)],
        "query_string": b"",
    }
    sent: list[dict] = []

    async def _receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(message):
        sent.append(message)

    result = await MCPAuthMiddleware(app=None)._apply_session_lifecycle(
        scope=scope,
        send=_send,
        request=Request(scope, _receive),
        method="tools/list",
        tenant_key=_SESSION_TENANT,
        user_id="u1",
        auth_method="jwt",
        mcp_session_id=None,
    )

    assert result is None
    assert sent[0]["status"] == 503
