# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.

"""BE-9394 — pins the ``template_write_paths`` extraction seam.

The create/update write paths were lifted out of ``template_service.py`` because that
module sat at its shrink-only budget plus the full tolerance band. The extraction is
only safe while three things stay true, and each is asserted here rather than left to
review:

1. ``TemplateService`` still OWNS the entry points — every caller and every existing
   test calls ``create_template_from_request`` / ``update_template_from_request`` on
   the service, so the delegators must actually route to the extracted functions and
   pass the service through as the first argument.
2. The public signatures are unchanged, so the extraction cannot silently alter the
   call contract.
3. The module does not import ``template_service`` at module scope. The allowlist
   constant deliberately stays in the parent (``tests/unit/test_write_discipline_hardening.py``
   imports it from there), so a module-scope import back would be a cycle — the
   update path imports it inside the function on purpose.

Edition Scope: Both.
"""

import ast
import inspect
from pathlib import Path

import pytest

from giljo_mcp.services import template_write_paths
from giljo_mcp.services.template_service import TemplateService


async def test_create_delegates_to_the_extracted_function(monkeypatch):
    """The service method must route to template_write_paths, passing itself through."""
    seen = {}

    async def _spy(service, session, data, tenant_key, created_by=None):
        seen.update(service=service, session=session, data=data, tenant_key=tenant_key, created_by=created_by)
        return "created-sentinel"

    monkeypatch.setattr(template_write_paths, "create_from_request", _spy)

    svc = TemplateService.__new__(TemplateService)  # no DB wiring needed for a routing assertion
    result = await svc.create_template_from_request("session-sentinel", "data-sentinel", "tk_test", "alice")

    assert result == "created-sentinel"
    assert seen["service"] is svc, "the calling service must be threaded through as the first argument"
    assert seen["session"] == "session-sentinel"
    assert seen["data"] == "data-sentinel"
    assert seen["tenant_key"] == "tk_test"
    assert seen["created_by"] == "alice"


async def test_update_delegates_to_the_extracted_function(monkeypatch):
    """Same seam for the update path, including the username passthrough."""
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
    """The extraction must not change the owning service's call contract."""
    params = list(inspect.signature(getattr(TemplateService, method_name)).parameters)
    assert params == expected_params


def test_module_does_not_import_template_service_at_module_scope():
    """A module-scope import back into template_service would be a cycle.

    The allowlist constant stays in template_service because
    tests/unit/test_write_discipline_hardening.py imports it from there, so the update
    path imports it INSIDE the function deliberately. Parsed rather than grepped so a
    matching string in a docstring or comment cannot pass or fail this by accident.
    """
    source = Path(template_write_paths.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_scope_imports = [
        node.module or ""
        for node in tree.body  # tree.body only -- function-local imports are nested deeper
        if isinstance(node, ast.ImportFrom)
    ]

    assert "giljo_mcp.services.template_service" not in module_scope_imports, (
        "template_write_paths must not import template_service at module scope -- "
        "template_service imports this module, so that would be an import cycle."
    )
