# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.tools.tool_accessor import ToolAccessor


def test_tool_accessor_initialization(mock_db_manager, mock_tenant_manager):
    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)

    assert accessor.db_manager is db_manager
    assert accessor.tenant_manager is mock_tenant_manager


def test_legacy_download_flow_tools_removed(mock_db_manager, mock_tenant_manager):
    db_manager, _session = mock_db_manager
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=mock_tenant_manager)

    assert not hasattr(accessor, "gil_fetch")
    assert not hasattr(accessor, "gil_import_productagents")
    assert not hasattr(accessor, "gil_import_personalagents")
    assert not hasattr(accessor, "gil_update_agents")
    assert not hasattr(accessor, "setup_slash_commands")
    assert not hasattr(accessor, "get_agent_download_url")
