# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json

import pytest

from giljo_mcp.exceptions import BaseGiljoError, ResourceNotFoundError, ValidationError
from giljo_mcp.tenant import TenantManager


@pytest.fixture
def real_key() -> str:
    return TenantManager.generate_tenant_key()


def test_a_tenant_key_in_a_context_does_not_survive_to_dict(real_key):
    err = ResourceNotFoundError(
        message="Product 'p-1' not found for tenant", context={"product_id": "p-1", "tenant_key": real_key}
    )

    assert real_key not in json.dumps(err.to_dict()), "the isolation key reached the wire"


def test_it_is_matched_by_shape_not_by_key_name(real_key):
    err = ValidationError(message="nope", context={"owner": real_key, "note": f"belongs to {real_key}"})

    body = json.dumps(err.to_dict())
    assert real_key not in body, "a differently-named field carried the key through"


def test_a_key_in_the_message_is_scrubbed_too(real_key):
    err = ValidationError(message=f"tenant {real_key} is not permitted here")

    assert real_key not in json.dumps(err.to_dict())


def test_nested_structures_are_reached(real_key):
    err = BaseGiljoError("x", context={"a": [{"deep": real_key}], "b": ("t", real_key)})

    assert real_key not in json.dumps(err.to_dict())


def test_the_context_still_carries_its_useful_fields(real_key):
    err = ResourceNotFoundError(
        message="Product 'p-1' not found for tenant",
        context={"product_id": "p-1", "tenant_key": real_key, "attempts": 3, "ok": False},
    )

    ctx = err.to_dict()["context"]
    assert ctx["product_id"] == "p-1", "a non-sensitive field was destroyed"
    assert ctx["attempts"] == 3, "a non-string value was destroyed"
    assert ctx["ok"] is False, "a falsy value was destroyed"
    assert err.to_dict()["error_code"] and err.to_dict()["message"]


def test_the_in_memory_context_is_left_alone(real_key):
    err = ResourceNotFoundError(message="x", context={"tenant_key": real_key})

    assert err.context["tenant_key"] == real_key
