# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import json

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


def test_the_refusal_payload_carries_the_message_not_the_str_rendering() -> None:
    err = _build_error()
    payload = err.as_refusal()

    assert payload["success"] is False
    assert payload["error"] == "PRODUCT_AMBIGUOUS"
    assert payload["message"] == err.message
    assert payload["message"] != str(err), "str(exc) appends (Context: {...}) including tenant_key"

    rendered = json.dumps(payload)
    assert "(Context:" not in rendered
    assert "tenant_key" not in rendered
    assert "tk_" not in rendered

    assert [p["name"] for p in payload["products"]] == ["Fixture Product Alpha", "Fixture Product Beta"]


def test_the_boundary_delegates_the_shape_instead_of_hand_rolling_it() -> None:
    source = inspect.getsource(_base._call_tool)

    assert "except CodedRefusalError as exc:" in source, "the coded-refusal handler moved -- re-point this test"
    assert "return exc.as_refusal()" in source, "the boundary must delegate the payload, not rebuild it"

    coded_branch = source.split("except CodedRefusalError as exc:", 1)[1].split("except ", 1)[0]
    assert "str(exc)" not in coded_branch, "str(exc) appends (Context: {...}) onto agent-facing content"
