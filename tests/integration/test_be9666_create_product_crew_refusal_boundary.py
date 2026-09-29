# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest
import pytest_asyncio

from giljo_mcp.services.template_write_paths import CrewNamingExhaustedError
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


@pytest_asyncio.fixture
async def product_client(monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    behaviour: dict[str, object] = {"raise": None}

    class _StubAccessor:
        async def create_product(self, name: str, **_kwargs):
            if behaviour["raise"] is not None:
                raise behaviour["raise"]
            return {"success": True, "product": {"id": "p-1", "name": name}}

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, behaviour
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager


async def test_unnameable_crew_returns_a_structured_refusal_not_an_error(product_client):
    new_client, behaviour = product_client
    behaviour["raise"] = CrewNamingExhaustedError(
        message="Too many agent crews named 'implementer' and siblings — rename or delete some agents first",
        context={"tenant_key": "tk_x"},
    )

    async with new_client() as session:
        result = await session.call_tool("create_product", {"name": "BE-9666 boundary"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"] == "CREW_NAMING_EXHAUSTED"
    assert "agents" in payload["message"].lower(), payload["message"]


async def test_the_refusal_message_carries_no_sql_or_constraint_name(product_client):
    new_client, behaviour = product_client
    behaviour["raise"] = CrewNamingExhaustedError(
        message=(
            "Could not name this product's agents because another change was happening "
            "at the same time. Please try creating the product again."
        ),
        context={"tenant_key": "tk_x", "product_id": "p-1"},
    )

    async with new_client() as session:
        result = await session.call_tool("create_product", {"name": "BE-9666 boundary race"})

    payload = _payload(result)
    for leak in ("uq_template_tenant_name_version", "INSERT INTO", "[SQL:", "[parameters:"):
        assert leak not in json.dumps(payload), f"the refusal leaked {leak!r}: {payload}"


async def test_an_unexpected_failure_is_still_sanitized_not_refused(product_client):
    new_client, behaviour = product_client
    behaviour["raise"] = RuntimeError("INSERT INTO agent_templates ... [parameters: ('secret',)]")

    async with new_client() as session:
        result = await session.call_tool("create_product", {"name": "BE-9666 boundary fault"})

    assert result.is_error is True
    text = _error_text(result)
    assert "secret" not in text and "[parameters:" not in text, text


async def test_create_product_still_succeeds_on_the_wire(product_client):
    new_client, behaviour = product_client
    behaviour["raise"] = None

    async with new_client() as session:
        result = await session.call_tool("create_product", {"name": "BE-9666 boundary ok"})

    assert result.is_error is False, _error_text(result)
    assert _payload(result)["success"] is True
