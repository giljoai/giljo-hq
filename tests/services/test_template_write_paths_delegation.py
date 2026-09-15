# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


import ast
import inspect
from pathlib import Path

import pytest

from giljo_mcp.services import template_write_paths
from giljo_mcp.services.template_service import TemplateService


async def test_create_delegates_to_the_extracted_function(monkeypatch):
    seen = {}

    async def _spy(service, session, data, tenant_key, created_by=None):
        seen.update(service=service, session=session, data=data, tenant_key=tenant_key, created_by=created_by)
        return "created-sentinel"

    monkeypatch.setattr(template_write_paths, "create_from_request", _spy)

    svc = TemplateService.__new__(TemplateService)
    result = await svc.create_template_from_request("session-sentinel", "data-sentinel", "tk_test", "alice")

    assert result == "created-sentinel"
    assert seen["service"] is svc, "the calling service must be threaded through as the first argument"
    assert seen["session"] == "session-sentinel"
    assert seen["data"] == "data-sentinel"
    assert seen["tenant_key"] == "tk_test"
    assert seen["created_by"] == "alice"


async def test_update_delegates_to_the_extracted_function(monkeypatch):
    seen = {}

    async def _spy(service, session, template_id, updates, tenant_key, username=None):
        seen.update(
            service=service,
            session=session,
            template_id=template_id,
            updates=updates,
            tenant_key=tenant_key,
            username=username,
        )
        return ("template-sentinel", ["is_active"])

    monkeypatch.setattr(template_write_paths, "update_from_request", _spy)

    svc = TemplateService.__new__(TemplateService)
    result = await svc.update_template_from_request("session-sentinel", "tpl-1", "updates-sentinel", "tk_test", "alice")

    assert result == ("template-sentinel", ["is_active"])
    assert seen["service"] is svc
    assert seen["template_id"] == "tpl-1"
    assert seen["username"] == "alice"


@pytest.mark.parametrize(
    ("method_name", "expected_params"),
    [
        ("create_template_from_request", ["self", "session", "data", "tenant_key", "created_by"]),
        (
            "update_template_from_request",
            ["self", "session", "template_id", "updates", "tenant_key", "username"],
        ),
    ],
)
def test_public_signatures_survived_the_extraction(method_name, expected_params):
    params = list(inspect.signature(getattr(TemplateService, method_name)).parameters)
    assert params == expected_params


def test_module_does_not_import_template_service_at_module_scope():
    source = Path(template_write_paths.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_scope_imports = [
        node.module or ""
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    ]

    assert "giljo_mcp.services.template_service" not in module_scope_imports, (
        "template_write_paths must not import template_service at module scope -- "
        "template_service imports this module, so that would be an import cycle."
    )
