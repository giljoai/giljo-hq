# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from src.giljo_mcp.services.project_service import ProjectService
from src.giljo_mcp.services.project_service._mcp_adapter_query_mixin import (
    _FORENSIC_MESSAGE_CAP,
    _MCP_LIST_PROJECT_CEILING,
    McpAdapterQueryMixin,
)
from src.giljo_mcp.services.project_service._mcp_list_diagnostics import log_payload_size_breakdown


class TestMcpAdapterQueryMixinModule:

    def test_mixin_class_importable(self):
        assert McpAdapterQueryMixin is not None

    def test_module_level_constants_present(self):
        assert isinstance(_MCP_LIST_PROJECT_CEILING, int)
        assert _MCP_LIST_PROJECT_CEILING > 0
        assert isinstance(_FORENSIC_MESSAGE_CAP, int)
        assert _FORENSIC_MESSAGE_CAP > 0

    def test_key_methods_defined_on_mixin(self):
        assert hasattr(McpAdapterQueryMixin, "list_projects_for_mcp")
        assert hasattr(McpAdapterQueryMixin, "_build_mcp_project_list")

    def test_log_payload_size_breakdown_now_lives_off_the_mixin(self):
        assert not hasattr(McpAdapterQueryMixin, "_log_payload_size_breakdown")
        assert callable(log_payload_size_breakdown)


class TestProjectServiceMroAfterSplit:

    def test_query_mixin_in_mro(self):
        mro_names = [cls.__name__ for cls in ProjectService.__mro__]
        assert "McpAdapterQueryMixin" in mro_names

    def test_list_projects_for_mcp_resolves_to_query_mixin(self):
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
        relocated = [
            "list_projects_for_mcp",
            "_build_mcp_project_list",
        ]
        for method_name in relocated:
            owners = [cls for cls in ProjectService.__mro__ if method_name in cls.__dict__]
            assert len(owners) == 1, f"{method_name} defined in multiple MRO classes: {owners}"

    def test_project_service_accessible_methods_unchanged(self):
        for method_name in (
            "list_projects_for_mcp",
            "create_project_for_mcp",
            "update_project_metadata_for_mcp",
        ):
            assert hasattr(ProjectService, method_name), f"ProjectService missing {method_name} after split"
