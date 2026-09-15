# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.





class TestWizardBearerOutput:

    def test_claude_prompt_uses_bearer(self):
        from api.endpoints.ai_tools import get_claude_code_config

        result = get_claude_code_config("https://localhost:7272", "gk_testkey123")
        assert "Authorization: Bearer gk_testkey123" in result
        assert "X-API-Key" not in result

    def test_codex_prompt_uses_env_var(self):
        from api.endpoints.ai_tools import get_codex_config

        result = get_codex_config("https://localhost:7272", "gk_testkey123")
        assert "--bearer-token-env-var GILJO_API_KEY" in result
        assert "X-API-Key" not in result




class TestMcpEndpointAcceptsBoth:

    def test_auth_middleware_exists(self):
        from unittest.mock import MagicMock

        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

        middleware = MCPAuthMiddleware(app=MagicMock())
        assert callable(middleware)
