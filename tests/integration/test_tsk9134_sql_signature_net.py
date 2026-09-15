# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

import pydantic
import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import _SANITIZED_TOOL_ERROR
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_dispatch import attach_registry_service_autospecs
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_SECRET_BIND = "secret-bind-value-tsk9134"

_LEAK_MARKERS = ("[SQL:", "[parameters:", "INSERT INTO", "DELETE FROM", "UPDATE ", _SECRET_BIND)


def _error_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _assert_no_leak(text: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"agent-facing error leaked {marker!r}: {text!r}"


@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    from unittest.mock import create_autospec

    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    accessor = create_autospec(ToolAccessor, instance=True)
    for attr_name in dir(ToolAccessor):
        if attr_name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"ok": True}

    attach_registry_service_autospecs(accessor, {"ok": True})

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, accessor
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _dispatch_create_task_raising(autospec_mcp, exc: BaseException):
    client, accessor = autospec_mcp
    accessor._task_service.create_task_for_mcp.side_effect = exc
    async with client() as session:
        return await session.call_tool("create_task", {"title": "ok", "description": "d"})




@pytest.mark.asyncio
async def test_valueerror_with_sqlalchemy_dump_is_sanitized(autospec_mcp):
    leaky = ValueError(
        "(psycopg2.errors.NotNullViolation) null value in column\n"
        "[SQL: INSERT INTO tasks (id, title) VALUES (%(id)s, %(title)s)]\n"
        f"[parameters: {{'id': 'uuid', 'title': '{_SECRET_BIND}'}}]"
    )
    result = await _dispatch_create_task_raising(autospec_mcp, leaky)
    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    assert "internal error" in text.lower() or _SANITIZED_TOOL_ERROR[:40] in text


@pytest.mark.asyncio
async def test_naive_wrapper_dml_plus_params_is_sanitized(autospec_mcp):
    leaky = ValueError(f"query failed: DELETE FROM projects WHERE id = 'x'; params={{'tenant': '{_SECRET_BIND}'}}")
    result = await _dispatch_create_task_raising(autospec_mcp, leaky)
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_typeerror_with_sql_dump_is_sanitized(autospec_mcp):
    leaky = TypeError(f"bad bind\n[SQL: UPDATE projects SET name=%(n)s]\n[parameters: {{'n': '{_SECRET_BIND}'}}]")
    result = await _dispatch_create_task_raising(autospec_mcp, leaky)
    assert result.is_error is True
    _assert_no_leak(_error_text(result))




@pytest.mark.asyncio
async def test_pydantic_validation_message_passes_through_unchanged(autospec_mcp):

    class _Tiny(pydantic.BaseModel):
        quantity: int

    try:
        _Tiny(quantity="not-an-int")
        raise AssertionError("expected pydantic ValidationError")
    except pydantic.ValidationError as exc:
        pyd_err = exc

    result = await _dispatch_create_task_raising(autospec_mcp, pyd_err)
    assert result.is_error is True
    text = _error_text(result)
    assert "quantity" in text
    assert "validation error" in text.lower()
    assert _SANITIZED_TOOL_ERROR[:40] not in text


@pytest.mark.asyncio
async def test_clean_validation_valueerror_passes_through_unchanged(autospec_mcp):
    clean = ValueError("core_features must be a non-empty list of short strings")
    result = await _dispatch_create_task_raising(autospec_mcp, clean)
    assert result.is_error is True
    text = _error_text(result)
    assert "core_features must be a non-empty list" in text
    assert _SANITIZED_TOOL_ERROR[:40] not in text


@pytest.mark.asyncio
async def test_sql_keyword_alone_in_prose_is_not_sanitized(autospec_mcp):
    prose = ValueError("Invalid choice: SELECT a plan from the pricing page and try again.")
    result = await _dispatch_create_task_raising(autospec_mcp, prose)
    assert result.is_error is True
    text = _error_text(result)
    assert "SELECT a plan from the pricing page" in text
    assert _SANITIZED_TOOL_ERROR[:40] not in text
