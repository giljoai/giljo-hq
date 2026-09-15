# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.endpoints.templates import models as template_models
from giljo_mcp.models.templates import AgentTemplate


pytestmark = pytest.mark.asyncio

_CAPPED = {
    "product_id": "PRODUCT_ID_MAX_LENGTH",
    "name": "NAME_MAX_LENGTH",
    "role": "ROLE_MAX_LENGTH",
    "cli_tool": "CLI_TOOL_MAX_LENGTH",
    "background_color": "BACKGROUND_COLOR_MAX_LENGTH",
    "tools": "TOOLS_MAX_LENGTH",
    "category": "CATEGORY_MAX_LENGTH",
}


def _column_length(field: str) -> int:
    return AgentTemplate.__table__.columns[field].type.length


def _request_cap(model, field: str) -> int | None:
    info = model.model_fields.get(field)
    if info is None:
        return None
    for meta in info.metadata:
        cap = getattr(meta, "max_length", None)
        if cap is not None:
            return cap
    return None


@pytest.mark.parametrize(("field", "constant"), sorted(_CAPPED.items()))
def test_the_cap_constant_matches_the_column_width(field: str, constant: str) -> None:
    assert getattr(template_models, constant) == _column_length(field), (
        f"{constant} has drifted from agent_templates.{field}'s String() width. "
        "Widen them together or the request model starts lying about the schema."
    )


@pytest.mark.parametrize("field", sorted(_CAPPED))
def test_create_caps_every_field_that_reaches_a_bounded_column(field: str) -> None:
    cap = _request_cap(template_models.TemplateCreate, field)
    assert cap is not None, (
        f"TemplateCreate.{field} reaches a String({_column_length(field)}) column with no "
        "max_length, so an over-long value returns a 500 instead of a 422"
    )
    assert cap == _column_length(field)


@pytest.mark.parametrize("field", ["name", "role", "cli_tool", "background_color"])
def test_update_caps_every_allowlisted_field_that_reaches_a_bounded_column(field: str) -> None:
    from giljo_mcp.services.template_service import _ALLOWED_TEMPLATE_UPDATE_FIELDS

    assert field in _ALLOWED_TEMPLATE_UPDATE_FIELDS, "guard on this test's premise"
    cap = _request_cap(template_models.TemplateUpdate, field)
    assert cap is not None, (
        f"TemplateUpdate.{field} is on the write allowlist and reaches a "
        f"String({_column_length(field)}) column with no max_length"
    )
    assert cap == _column_length(field)


async def test_an_over_long_value_is_refused_at_the_boundary_not_by_the_database(api_client, auth_headers) -> None:
    product = await api_client.post(
        "/api/v1/products/",
        headers=auth_headers,
        json={"name": "BE-9610a2 caps fixture", "description": "field-cap boundary"},
    )
    assert product.status_code == 200, product.text

    resp = await api_client.post(
        "/api/v1/templates/",
        headers=auth_headers,
        json={
            "product_id": product.json()["id"],
            "role": "implementer",
            "cli_tool": "x" * (template_models.CLI_TOOL_MAX_LENGTH + 1),
        },
    )

    assert resp.status_code == 422, f"expected a 422 naming the field, got {resp.status_code}: {resp.text}"
    assert "cli_tool" in resp.text
