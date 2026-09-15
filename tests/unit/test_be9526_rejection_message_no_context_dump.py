# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

from api.endpoints.mcp_tools import _base
from giljo_mcp.services.product_service import ProductAmbiguousError


def _build_error() -> ProductAmbiguousError:
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
    rendered = str(_build_error())
    assert "(Context:" in rendered
    assert "tenant_key" in rendered


def test_message_is_clean_of_the_context_dump() -> None:
    err = _build_error()
    assert "(Context:" not in err.message
    assert "tenant_key" not in err.message
    assert "tk_" not in err.message


def test_boundary_returns_message_not_str() -> None:
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
