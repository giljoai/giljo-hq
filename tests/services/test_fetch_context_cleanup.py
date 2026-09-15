# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect


class TestApplyUserConfigRemoved:

    def test_fetch_context_signature_no_apply_user_config(self):
        from giljo_mcp.tools.context_tools.fetch_context import fetch_context

        sig = inspect.signature(fetch_context)
        params = list(sig.parameters.keys())
        assert "apply_user_config" not in params, (
            f"apply_user_config should be removed from fetch_context signature. Current params: {params}"
        )

    def test_tool_accessor_fetch_context_no_apply_user_config(self):
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        sig = inspect.signature(ToolAccessor.get_context)
        params = list(sig.parameters.keys())
        assert "apply_user_config" not in params, (
            f"apply_user_config should be removed from ToolAccessor.get_context. Current params: {params}"
        )


class TestToolAccessorCategoriesDefault:

    def test_tool_accessor_no_all_fallback(self):
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        source = inspect.getsource(ToolAccessor.get_context)
        assert '["all"]' not in source, (
            "ToolAccessor.get_context should not fall back to ['all']. "
            "Let fetch_context handle None with its existing SINGLE_CATEGORY_REQUIRED error."
        )
