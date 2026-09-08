# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9526: the PRODUCT_AMBIGUOUS rejection must not leak the raw context dict.

A ``create_project`` refusal returned the hand-written guidance message
followed by ``(Context: {'operation': ..., 'tenant_key': 'tk_...',
'products': [...]})``.

Two defects in one string:

1. ``BaseGiljoError.__str__`` appends ``(Context: {self.context})`` for every
   error in the product. That is fine for a log line and wrong for agent-facing
   content -- and BE-9523b's handler was returning ``str(exc)``.
2. The dumped dict carries ``tenant_key``. The caller owns that tenant, so this
   is not a cross-tenant leak, but agent transcripts get pasted into issues and
   chat logs, and a tenant key does not belong in one. It also repeats the
   product list already carried structurally in ``products``.

The fix is to return ``exc.message`` -- the message the project deliberately
authored -- rather than the ``__str__`` rendering that decorates it.

``__str__`` itself is deliberately NOT changed: it is longstanding behaviour
across every error in the codebase and its log output is useful. This test pins
the boundary, which is the only place the distinction matters.
"""

from __future__ import annotations

import inspect

from api.endpoints.mcp_tools import _base
from giljo_mcp.services.product_service import ProductAmbiguousError


def _build_error() -> ProductAmbiguousError:
    """A refusal with the same shape the gate produces (fixture data)."""
    products = [
        {"id": "00000000-0000-4000-8000-000000000001", "name": "Fixture Product Alpha", "is_active": True},
        {"id": "00000000-0000-4000-8000-000000000002", "name": "Fixture Product Beta", "is_active": False},
    ]
    return ProductAmbiguousError(
        products=products,
        operation="create_project",
        tenant_key="tk_testProductAmbiguity123456789012",
    )


def test_str_still_carries_context_for_logs() -> None:
    """Pin the UNCHANGED half: __str__ keeps decorating, because logs want it.

    If this ever fails, someone widened the fix into every error message in the
    product. That is a separate, deliberate decision -- not a side effect.
    """
    rendered = str(_build_error())
    assert "(Context:" in rendered
    assert "tenant_key" in rendered


def test_message_is_clean_of_the_context_dump() -> None:
    """The authored message must be exactly what the project wrote."""
    err = _build_error()
    assert "(Context:" not in err.message
    assert "tenant_key" not in err.message
    assert "tk_" not in err.message


def test_boundary_returns_message_not_str() -> None:
    """The ProductAmbiguousError branch must return exc.message, never str(exc).

    Targeted at that branch specifically: `_call_tool` has TWO structured-rejection
    handlers returning `"error": exc.code`, and a naive first-match would assert
    against CursorRejectedError's line instead -- which is exactly what the first
    draft of this test did.

    CursorRejectedError is DELIBERATELY left on str(exc). Its context is
    {"operation": "list_cursor", "error": code} -- no tenant key, nothing
    sensitive, so the tail is redundant noise rather than a leak. Changing it
    would be an observable behaviour change with no reproduced harm behind it.
    """
    source = inspect.getsource(_base._call_tool)
    lines = source.splitlines()

    idx = next(
        (i for i, ln in enumerate(lines) if "except ProductAmbiguousError" in ln),
        None,
    )
    assert idx is not None, "the ProductAmbiguousError handler moved -- re-point this test"

    branch = "\n".join(lines[idx : idx + 10])
    ret = next(ln for ln in branch.splitlines() if '"error": exc.code' in ln)

    assert "exc.message" in ret, f"boundary must return exc.message, got: {ret.strip()}"
    assert "str(exc)" not in ret, "str(exc) appends (Context: {...}) including tenant_key onto agent-facing content"
