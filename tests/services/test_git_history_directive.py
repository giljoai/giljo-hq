# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGitHistoryDirective:

    @pytest.mark.asyncio
    async def test_empty_db_returns_directive(self):
        from giljo_mcp.tools.context_tools.get_git_history import get_git_history

        mock_product = MagicMock()
        mock_product.id = "prod-123"
        mock_product.tenant_key = "tk_test"
        mock_product.product_memory = {}
        mock_product.project_path = "/home/user/project"

        mock_session = AsyncMock()
        mock_session.info = {}

        mock_result_product = MagicMock()
        mock_result_product.scalar_one_or_none.return_value = mock_product

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result_product
            return MagicMock(scalars=lambda: MagicMock(all=list))

        mock_session.execute = mock_execute

        with (
            patch("giljo_mcp.tools.context_tools.get_git_history.SettingsService") as mock_settings_cls,
            patch("giljo_mcp.tools.context_tools.get_git_history.ProductMemoryService") as mock_svc_cls,
        ):
            mock_settings_cls.return_value.git_integration_enabled = AsyncMock(return_value=True)
            mock_svc = MagicMock()
            mock_svc.get_git_history = AsyncMock(return_value=[])
            mock_svc_cls.return_value = mock_svc

            result = await get_git_history(
                product_id="prod-123",
                tenant_key="tk_test",
                commits=25,
                session=mock_session,
            )

        assert "directive" in result, "Empty DB should return a directive"
        assert result["directive"]["action"] == "fetch_from_local_repo"
        assert "git log" in result["directive"]["command"]
        assert "-25" in result["directive"]["command"]

    @pytest.mark.asyncio
    async def test_directive_commit_count_matches_depth(self):
        from giljo_mcp.tools.context_tools.get_git_history import get_git_history

        mock_product = MagicMock()
        mock_product.id = "prod-123"
        mock_product.tenant_key = "tk_test"
        mock_product.product_memory = {}
        mock_product.project_path = "/project"

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_product

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result
            return MagicMock(scalars=lambda: MagicMock(all=list))

        mock_session.execute = mock_execute

        with (
            patch("giljo_mcp.tools.context_tools.get_git_history.SettingsService") as mock_settings_cls,
            patch("giljo_mcp.tools.context_tools.get_git_history.ProductMemoryService") as mock_svc_cls,
        ):
            mock_settings_cls.return_value.git_integration_enabled = AsyncMock(return_value=True)
            mock_svc = MagicMock()
            mock_svc.get_git_history = AsyncMock(return_value=[])
            mock_svc_cls.return_value = mock_svc

            result = await get_git_history(
                product_id="prod-123",
                tenant_key="tk_test",
                commits=50,
                session=mock_session,
            )

        assert "-50" in result["directive"]["command"]

    @pytest.mark.asyncio
    async def test_git_disabled_returns_directive(self):
        from giljo_mcp.tools.context_tools.get_git_history import get_git_history

        mock_product = MagicMock()
        mock_product.id = "prod-123"
        mock_product.tenant_key = "tk_test"
        mock_product.product_memory = {}
        mock_product.project_path = "/project"

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_product
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("giljo_mcp.tools.context_tools.get_git_history.SettingsService") as mock_settings_cls:
            mock_settings_cls.return_value.git_integration_enabled = AsyncMock(return_value=False)
            result = await get_git_history(
                product_id="prod-123",
                tenant_key="tk_test",
                commits=25,
                session=mock_session,
            )

        assert "directive" in result, "Disabled git should return directive"
        assert result["directive"]["action"] == "fetch_from_local_repo"

    @pytest.mark.asyncio
    async def test_populated_db_returns_data_no_directive(self):
        from giljo_mcp.tools.context_tools.get_git_history import get_git_history

        mock_product = MagicMock()
        mock_product.id = "prod-123"
        mock_product.tenant_key = "tk_test"
        mock_product.product_memory = {}

        mock_session = AsyncMock()
        mock_session.info = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_product

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_result
            return MagicMock(scalars=lambda: MagicMock(all=list))

        mock_session.execute = mock_execute

        fake_commits = [
            {"hash": "abc123", "message": "feat: test", "author": "dev", "timestamp": "2026-01-01"},
            {"hash": "def456", "message": "fix: bug", "author": "dev", "timestamp": "2026-01-02"},
        ]

        with (
            patch("giljo_mcp.tools.context_tools.get_git_history.SettingsService") as mock_settings_cls,
            patch("giljo_mcp.tools.context_tools.get_git_history.ProductMemoryService") as mock_svc_cls,
        ):
            mock_settings_cls.return_value.git_integration_enabled = AsyncMock(return_value=True)
            mock_svc = MagicMock()
            mock_svc.get_git_history = AsyncMock(return_value=fake_commits)
            mock_svc_cls.return_value = mock_svc

            result = await get_git_history(
                product_id="prod-123",
                tenant_key="tk_test",
                commits=25,
                session=mock_session,
            )

        assert "directive" not in result, "Populated DB should NOT return directive"
        assert result["metadata"]["git_integration_enabled"] is True
        assert len(result["data"]) == 2


class TestFetchContextDirectivePropagation:

    @pytest.mark.asyncio
    async def test_fetch_context_propagates_git_directive(self):
        from giljo_mcp.tools.context_tools.fetch_context import fetch_context

        mock_git_result = {
            "source": "git_history",
            "depth": 25,
            "data": [],
            "directive": {
                "action": "fetch_from_local_repo",
                "command": "git log --oneline -25",
                "note": "Git history is not stored on the server.",
            },
            "metadata": {},
        }

        with patch("giljo_mcp.tools.context_tools.fetch_context._fetch_category", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_git_result

            result = await fetch_context(
                product_id="prod-123",
                tenant_key="tk_test",
                categories=["git_history"],
            )

        assert "directive" in result, "fetch_context must propagate directive from inner tool"
        assert "git_history" in result["directive"]
        assert result["directive"]["git_history"]["action"] == "fetch_from_local_repo"
        assert "-25" in result["directive"]["git_history"]["command"]

    @pytest.mark.asyncio
    async def test_fetch_context_omits_directive_when_data_present(self):
        from giljo_mcp.tools.context_tools.fetch_context import fetch_context

        mock_git_result = {
            "source": "git_history",
            "depth": 25,
            "data": [{"hash": "abc123", "message": "feat: test"}],
            "metadata": {},
        }

        with patch("giljo_mcp.tools.context_tools.fetch_context._fetch_category", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_git_result

            result = await fetch_context(
                product_id="prod-123",
                tenant_key="tk_test",
                categories=["git_history"],
            )

        assert "directive" not in result, "No directive when data is present"
