# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools import _base
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_SECRET = "hunter2-do-not-echo"


class _Capped(BaseModel):
    summary: str = Field(max_length=5)


def _text(result) -> str:
    return "\n".join(getattr(block, "text", "") or "" for block in result.content or [])


@pytest.mark.asyncio
async def test_pydantic_validation_reply_does_not_echo_input_value(monkeypatch) -> None:
    async def _raises(**_kwargs):
        _Capped(summary=_SECRET)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "tenant-9842")
    monkeypatch.setattr(_base, "_set_tenant_context", lambda tenant_key: None)
    monkeypatch.setattr(_base, "_get_tool_accessor", MagicMock)
    monkeypatch.setattr(_base, "_resolve_tool_func", lambda accessor, name: _raises)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_roadmap", {})

    text = _text(result)
    assert "summary" in text and "at most 5" in text, f"the reply must still say what was wrong: {text!r}"
    assert "input_value" not in text, f"the reply echoes the caller's input: {text!r}"
    assert _SECRET not in text, f"the reply echoes the caller's input: {text!r}"
