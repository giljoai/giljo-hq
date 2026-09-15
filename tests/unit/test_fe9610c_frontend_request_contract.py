# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.endpoints.templates import crud as templates_crud
from api.endpoints.templates.models import TemplateCreate


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "frontend" / "src" / "services"

ENDPOINTS = [
    ("/api/v1/templates/stats/active-count", templates_crud.get_active_count),
    ("/api/v1/templates/import-defaults", templates_crud.import_default_agent_templates),
]


def _required_query_params(handler) -> set[str]:
    import inspect

    from fastapi import Query
    from pydantic_core import PydanticUndefined

    query_type = type(Query(...))
    required = set()
    for name, param in inspect.signature(handler).parameters.items():
        default = param.default
        if isinstance(default, query_type) and default.default in (Ellipsis, PydanticUndefined):
            required.add(name)
    return required


def _client_entry(path_literal: str) -> str:
    needle = f"'{path_literal}'"
    for source_file in sorted(SERVICES_DIR.rglob("*.js")):
        source = source_file.read_text(encoding="utf-8")
        idx = source.find(needle)
        if idx == -1:
            continue
        start = source.rfind("\n", 0, source.rfind("\n", 0, idx) + 1)
        end = source.index("\n", source.index(")", idx))
        return source[start:end]
    raise AssertionError(f"no frontend service call to {path_literal} -- update this test")


@pytest.mark.parametrize(("path_literal", "handler"), ENDPOINTS, ids=lambda v: getattr(v, "__name__", v))
def test_api_js_supplies_every_required_query_param(path_literal, handler):
    required = _required_query_params(handler)
    assert required, f"{handler.__name__} has no required query params -- update ENDPOINTS"

    entry = _client_entry(path_literal)
    missing = {name for name in required if name not in entry}

    assert not missing, (
        f"the frontend calls {path_literal} without the required query "
        f"parameter(s) {sorted(missing)}. The server answers 422. Entry:\n{entry}"
    )


def test_template_create_payload_carries_every_required_body_field():
    required = {name for name, field in TemplateCreate.model_fields.items() if field.is_required()}
    assert "product_id" in required, "BE-9610a made product_id required; this test assumes it"

    callers = [
        p
        for p in (REPO_ROOT / "frontend" / "src").rglob("*.vue")
        if "api.templates.create(" in p.read_text(encoding="utf-8")
    ]
    assert callers, "no frontend caller of api.templates.create -- update this test"

    for caller in callers:
        body = caller.read_text(encoding="utf-8")
        missing = {name for name in required if not re.search(rf"\b{re.escape(name)}\s*:", body)}
        assert not missing, (
            f"{caller.relative_to(REPO_ROOT)} builds the create payload without required "
            f"field(s) {sorted(missing)}. The server answers 422."
        )


def test_list_templates_product_scope_is_optional_on_purpose():
    required = _required_query_params(templates_crud.list_templates)
    assert "product_id" not in required

    entry = _client_entry("/api/v1/templates/")
    assert "product_id" in entry, "the agents list must be able to scope to a product; the entry is:\n" + entry
