# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9134 -- SQL-signature net at the MCP-boundary ValueError/TypeError re-raise.

Museum rule: these tests are authored BEFORE the production change and observed
RED for the predicted reason (a ``ValueError``/``TypeError`` carrying SQL text +
bind parameters reaches the agent VERBATIM through the ``_CLEAN_VALIDATION_ERRORS``
re-raise path), and GREEN once the signature net is added. The captured fail-first
output is recorded in the PR body before the production diff.

Defense-in-depth context (from BE-3006d): ``api/endpoints/mcp_tools/_base.py``
re-raises ``ValueError``/``TypeError`` verbatim because pydantic v2
``ValidationError`` IS a ``ValueError`` and its message is the agent-facing
contract. BE-3006d already sanitizes actual driver exceptions (``SQLAlchemyError``
& friends hit the ``except Exception`` catch-all). The gap this closes: a FUTURE
wrapper that stuffs SQL text / bind params into a plain ``ValueError`` below the
boundary would leak them straight to agents through the verbatim path. The net
sanitizes ONLY messages carrying a SQL/bind-parameter leak signature; every
legitimate validation message passes through UNCHANGED.

The failing layer is the FastMCP ``@mcp.tool`` wrapper + the single ``_call_tool``
dispatch chokepoint, so every test drives the REAL transport
(``create_connected_server_and_client_session``) and reads the wire error text --
not the service layer in isolation (the BE-5042 lesson).

Parallel-safe: the autospec harness needs no DB; tenant keys are freshly
generated per test; no module-level mutable state (monkeypatch + fixture
teardown restore ``app_state``). Edition Scope: Both.
"""

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


# A unique sentinel planted as a bind-parameter value. If it ever reaches the
# agent-facing wire text, a real bind parameter leaked -- the exact failure mode.
_SECRET_BIND = "secret-bind-value-tsk9134"

# Substrings that would prove a raw SQL/driver leak crossed the boundary.
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
    """Autospec ToolAccessor + tenant resolution on the in-memory transport
    (mirrors test_be3006d_mcp_boundary_validation.autospec_mcp). Yields a client
    factory and the accessor so a test can plant a side_effect on a terminal
    service method and drive it through the real dispatch chokepoint."""
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
    """Plant ``exc`` on the create_task terminal method and dispatch through the
    transport; return the agent-facing wire result. create_task dispatches to
    ``_task_service.create_task_for_mcp`` (BE-3010b), the same terminal method the
    BE-3006d sanitization test plants on."""
    client, accessor = autospec_mcp
    accessor._task_service.create_task_for_mcp.side_effect = exc
    async with client() as session:
        return await session.call_tool("create_task", {"title": "ok", "description": "d"})


# ---------------------------------------------------------------------------
# RED-before-fix: SQL text + bind params in a ValueError/TypeError must be
# sanitized, not surfaced verbatim.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valueerror_with_sqlalchemy_dump_is_sanitized(autospec_mcp):
    """The BE-3006d leak shape ('[SQL: ...] [parameters: ...]') carried by a PLAIN
    ValueError (not a SQLAlchemyError) reaches the agent verbatim today -> RED.
    After the net it is logged server-side and replaced with the generic message."""
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
    """A naive future wrapper that f-strings a DML statement + a params dump into a
    ValueError (no SQLAlchemy brackets) also leaks verbatim today -> RED. The net's
    DML-statement + params-token branch catches it."""
    leaky = ValueError(f"query failed: DELETE FROM projects WHERE id = 'x'; params={{'tenant': '{_SECRET_BIND}'}}")
    result = await _dispatch_create_task_raising(autospec_mcp, leaky)
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_typeerror_with_sql_dump_is_sanitized(autospec_mcp):
    """TypeError is also in _CLEAN_VALIDATION_ERRORS, so the same leak shape carried
    by a TypeError must be sanitized -> RED before the net."""
    leaky = TypeError(f"bad bind\n[SQL: UPDATE projects SET name=%(n)s]\n[parameters: {{'n': '{_SECRET_BIND}'}}]")
    result = await _dispatch_create_task_raising(autospec_mcp, leaky)
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


# ---------------------------------------------------------------------------
# GREEN before AND after: legitimate validation messages pass through UNCHANGED
# (the load-bearing UNTOUCHABLE -- pydantic messages are the agent-facing contract).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pydantic_validation_message_passes_through_unchanged(autospec_mcp):
    """A real pydantic v2 ValidationError (a ValueError) surfaces VERBATIM -- the
    field/type detail the agent needs to self-correct is never sanitized."""

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
    # The actionable pydantic detail survives; it was NOT replaced by the net.
    assert "quantity" in text
    assert "validation error" in text.lower()
    assert _SANITIZED_TOOL_ERROR[:40] not in text


@pytest.mark.asyncio
async def test_clean_validation_valueerror_passes_through_unchanged(autospec_mcp):
    """A plain, clean validator-style ValueError (no SQL, no params dump) still
    surfaces verbatim -- the net must not over-sanitize legitimate rejections."""
    clean = ValueError("core_features must be a non-empty list of short strings")
    result = await _dispatch_create_task_raising(autospec_mcp, clean)
    assert result.is_error is True
    text = _error_text(result)
    assert "core_features must be a non-empty list" in text
    assert _SANITIZED_TOOL_ERROR[:40] not in text


@pytest.mark.asyncio
async def test_sql_keyword_alone_in_prose_is_not_sanitized(autospec_mcp):
    """A validation message that merely MENTIONS a SQL keyword (echoing agent input
    or human prose) but carries no bind-parameter dump must NOT be sanitized -- the
    keyword alone is not a leak, so the pydantic contract is preserved."""
    prose = ValueError("Invalid choice: SELECT a plan from the pricing page and try again.")
    result = await _dispatch_create_task_raising(autospec_mcp, prose)
    assert result.is_error is True
    text = _error_text(result)
    assert "SELECT a plan from the pricing page" in text
    assert _SANITIZED_TOOL_ERROR[:40] not in text
