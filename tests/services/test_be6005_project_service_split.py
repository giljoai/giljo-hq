# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Structural smoke tests for BE-6005 project_service split.

Verifies that the behavior-preserving extraction of McpAdapterQueryMixin
from _mcp_adapter_mixin.py is importable, MRO-resolved correctly, and that
the relocated methods remain accessible on ProjectService.

No database access needed — these are module/class-shape checks only.
"""

from src.giljo_mcp.services.project_service import ProjectService
from src.giljo_mcp.services.project_service._mcp_adapter_query_mixin import (
    _FORENSIC_MESSAGE_CAP,
    _MCP_LIST_PROJECT_CEILING,
    McpAdapterQueryMixin,
)
from src.giljo_mcp.services.project_service._mcp_list_diagnostics import log_payload_size_breakdown


class TestMcpAdapterQueryMixinModule:
    """Verify the new mixin module is importable with expected exports."""

    def test_mixin_class_importable(self):
        """McpAdapterQueryMixin must be importable from its own module."""
        assert McpAdapterQueryMixin is not None

    def test_module_level_constants_present(self):
        """Module-level helpers relocated with the list path must be present."""
        assert isinstance(_MCP_LIST_PROJECT_CEILING, int)
        assert _MCP_LIST_PROJECT_CEILING > 0
        assert isinstance(_FORENSIC_MESSAGE_CAP, int)
        assert _FORENSIC_MESSAGE_CAP > 0

    def test_key_methods_defined_on_mixin(self):
        """The relocated methods must be directly defined on McpAdapterQueryMixin."""
        assert hasattr(McpAdapterQueryMixin, "list_projects_for_mcp")
        assert hasattr(McpAdapterQueryMixin, "_build_mcp_project_list")

    def test_log_payload_size_breakdown_now_lives_off_the_mixin(self):
        """BE-9471: extracted to a plain function (no `self`) to free 800-line headroom.

        Was a BE-6005 method on this mixin; BE-9471 moved it to
        ``_mcp_list_diagnostics`` (same pattern BE-9468 already used for
        ``_mcp_list_bounds``) rather than growing a module already at cap.
        Behavior-neutral -- same log line, same call, one module over.
        """
        assert not hasattr(McpAdapterQueryMixin, "_log_payload_size_breakdown")
        assert callable(log_payload_size_breakdown)


class TestProjectServiceMroAfterSplit:
    """Verify MRO resolution after the 4th base (McpAdapterQueryMixin) was added."""

    def test_query_mixin_in_mro(self):
        """McpAdapterQueryMixin must appear in ProjectService's MRO."""
        mro_names = [cls.__name__ for cls in ProjectService.__mro__]
        assert "McpAdapterQueryMixin" in mro_names

    def test_list_projects_for_mcp_resolves_to_query_mixin(self):
        """list_projects_for_mcp must resolve to McpAdapterQueryMixin, not another base.

        Uses class name comparison (not `is`) to avoid src./package path aliasing.
        """
        owner = None
        for cls in ProjectService.__mro__:
            if "list_projects_for_mcp" in cls.__dict__:
                owner = cls
                break
        assert owner is not None
        assert owner.__name__ == "McpAdapterQueryMixin", (
            f"list_projects_for_mcp owned by {owner.__name__}, expected McpAdapterQueryMixin"
        )

    def test_create_project_for_mcp_still_on_original_mixin(self):
        """create_project_for_mcp (write path) must NOT have moved — stays in McpAdapterMixin.

        Uses class name comparison (not `is`) to avoid src./package path aliasing.
        """
        owner = None
        for cls in ProjectService.__mro__:
            if "create_project_for_mcp" in cls.__dict__:
                owner = cls
                break
        assert owner is not None
        assert owner.__name__ == "McpAdapterMixin", (
            f"create_project_for_mcp owned by {owner.__name__}, expected McpAdapterMixin"
        )

    def test_no_duplicate_method_owners_for_relocated_methods(self):
        """Each relocated method must appear in exactly ONE class in the MRO."""
        relocated = [
            "list_projects_for_mcp",
            "_build_mcp_project_list",
        ]
        for method_name in relocated:
            owners = [cls for cls in ProjectService.__mro__ if method_name in cls.__dict__]
            assert len(owners) == 1, f"{method_name} defined in multiple MRO classes: {owners}"

    def test_project_service_accessible_methods_unchanged(self):
        """The public API surface of ProjectService must include all relocated methods."""
        for method_name in (
            "list_projects_for_mcp",
            "create_project_for_mcp",
            "update_project_metadata_for_mcp",
        ):
            assert hasattr(ProjectService, method_name), f"ProjectService missing {method_name} after split"
