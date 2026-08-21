# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.

"""BE-9394 — pins the ``template_lifecycle`` extraction seam.

The soft-delete lifecycle (trash / list-trashed / restore / reap) was lifted out of
``template_service.py`` alongside the write paths, which took the parent back under
the flat 800-line cap. The behaviour is unchanged and is covered by the suites that
already own it — ``test_be6137_template_softdelete_recover.py`` and
``test_tsk6132_softdelete_reaper.py`` both call these through the service and pass
untouched. What those suites do NOT pin is the seam itself, which is what this file
adds: the service still owns the entry points, the signatures did not drift, and the
extracted module stays free of an import cycle back to its parent.

Edition Scope: Both.
"""

import ast
import inspect
from pathlib import Path

import pytest

from giljo_mcp.services import template_lifecycle
from giljo_mcp.services.template_service import TemplateService


@pytest.mark.parametrize(
    ("method_name", "call_args"),
    [
        ("purge_expired_deleted_templates", ("tk_test",)),
        ("restore_template", ("tpl-1", "tk_test")),
        ("list_deleted_templates", ("tk_test",)),
    ],
)
async def test_service_methods_delegate_to_the_extracted_module(monkeypatch, method_name, call_args):
    """Each lifecycle entry point must route out, threading the service through."""
    seen = {}

    async def _spy(service, *args):
        seen.update(service=service, args=args)
        return "sentinel"

    monkeypatch.setattr(template_lifecycle, method_name, _spy)

    svc = TemplateService.__new__(TemplateService)  # no DB wiring needed for a routing assertion
    result = await getattr(svc, method_name)(*call_args)

    assert result == "sentinel"
    assert seen["service"] is svc, "the calling service must be threaded through as the first argument"
    assert seen["args"] == call_args


async def test_delete_template_delegates_with_its_session(monkeypatch):
    """delete_template is the one that also carries the caller-owned session."""
    seen = {}

    async def _spy(service, session, template_id, tenant_key):
        seen.update(service=service, session=session, template_id=template_id, tenant_key=tenant_key)
        return True

    monkeypatch.setattr(template_lifecycle, "delete_template", _spy)

    svc = TemplateService.__new__(TemplateService)
    assert await svc.delete_template("session-sentinel", "tpl-1", "tk_test") is True
    assert seen["service"] is svc
    assert seen["session"] == "session-sentinel"


@pytest.mark.parametrize(
    ("method_name", "expected_params"),
    [
        ("purge_expired_deleted_templates", ["self", "tenant_key"]),
        ("delete_template", ["self", "session", "template_id", "tenant_key"]),
        ("restore_template", ["self", "template_id", "tenant_key"]),
        ("list_deleted_templates", ["self", "tenant_key"]),
    ],
)
def test_public_signatures_survived_the_extraction(method_name, expected_params):
    """The extraction must not change the owning service's call contract."""
    params = list(inspect.signature(getattr(TemplateService, method_name)).parameters)
    assert params == expected_params


def test_module_does_not_import_template_service_at_module_scope():
    """template_service imports this module, so an import back would be a cycle.

    Parsed rather than grepped so a matching string in a docstring or comment cannot
    pass or fail this by accident.
    """
    tree = ast.parse(Path(template_lifecycle.__file__).read_text(encoding="utf-8"))
    module_scope_imports = [node.module or "" for node in tree.body if isinstance(node, ast.ImportFrom)]

    assert "giljo_mcp.services.template_service" not in module_scope_imports, (
        "template_lifecycle must not import template_service at module scope."
    )
