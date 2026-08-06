# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for the post-6f702526a contract change:

`ProjectService.list_projects_for_mcp()` no longer embeds the
`project_types` taxonomy in its response. Callers must use the
`GET /api/taxonomy-types/` endpoint for taxonomy discovery.

The `_get_valid_project_types` helper is intentionally retained so
`update_project_metadata_for_mcp` can still surface a "Valid types: ..."
validation error message when an unknown project_type is supplied.

These tests focus on BEHAVIOR (the response contract), not implementation.
Tenant isolation is preserved by passing an explicit tenant_key per call.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.services.project_service import ProjectService


_TENANT_A = "tenant-aaa"
_TENANT_B = "tenant-bbb"


def _make_service(tenant_key: str) -> ProjectService:
    """Build a ProjectService with a stub db_manager + tenant_manager.

    Mirrors the mock pattern used in
    tests/unit/test_tool_accessor_list_update_project.py so we do not
    introduce a new test infrastructure pattern.
    """
    db_manager = Mock()
    mock_session = AsyncMock()
    db_manager.get_session_async = Mock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.info = {}  # tenant_session_context save/restore target
    mock_result = Mock()
    mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
    mock_session.execute = AsyncMock(return_value=mock_result)

    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)

    return ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
    )


_PRODUCT_SERVICE_PATH = "giljo_mcp.services.product_service.ProductService"


class TestListProjectsForMcpDropsProjectTypes:
    """list_projects_for_mcp() must NOT embed `project_types` after 6f702526a."""

    @pytest.mark.asyncio
    async def test_summary_only_response_has_no_project_types_key(self):
        service = _make_service(tenant_key=_TENANT_A)
        mock_product = Mock()
        mock_product.id = "prod-001"

        with (
            patch.object(service, "list_projects", new_callable=AsyncMock, return_value=[]),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(service, "_build_mcp_project_list", new_callable=AsyncMock, return_value=[]),
        ):
            mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)

            result = await service.list_projects_for_mcp(
                summary_only=True,
                tenant_key=_TENANT_A,
            )

        assert "project_types" not in result, (
            "list_projects_for_mcp() must NOT embed `project_types` (commit 6f702526a). "
            f"Got keys: {sorted(result.keys())}"
        )
        # Positive contract: keys we do still promise.
        assert result["success"] is True
        assert result["product_id"] == "prod-001"
        assert "projects" in result
        assert "count" in result
        assert "depth" in result

    @pytest.mark.asyncio
    async def test_full_depth_response_has_no_project_types_key(self):
        service = _make_service(tenant_key=_TENANT_A)
        mock_product = Mock()
        mock_product.id = "prod-001"

        with (
            patch.object(service, "list_projects", new_callable=AsyncMock, return_value=[]),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(service, "_build_mcp_project_list", new_callable=AsyncMock, return_value=[]),
        ):
            mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)

            result = await service.list_projects_for_mcp(
                summary_only=False,
                depth=3,
                tenant_key=_TENANT_A,
            )

        assert "project_types" not in result
        assert result["depth"] == 3

    @pytest.mark.asyncio
    async def test_helper_not_invoked_during_list(self):
        """The taxonomy helper must not be called from list_projects_for_mcp.

        This is the perf reason for the strip: avoid an extra DB roundtrip
        on every list_projects call.
        """
        service = _make_service(tenant_key=_TENANT_A)
        mock_product = Mock()
        mock_product.id = "prod-001"

        with (
            patch.object(service, "list_projects", new_callable=AsyncMock, return_value=[]),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(service, "_build_mcp_project_list", new_callable=AsyncMock, return_value=[]),
            patch.object(service, "_get_valid_project_types", new_callable=AsyncMock, return_value=[]) as helper,
        ):
            mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)
            await service.list_projects_for_mcp(summary_only=True, tenant_key=_TENANT_A)

        helper.assert_not_called()

    @pytest.mark.asyncio
    async def test_tenant_isolation_each_tenant_sees_only_its_own_product(self):
        """Cross-tenant smoke check: tenant_key flows through unchanged.

        Each tenant resolves a different active product; the response shape
        contract (no `project_types`) is uniform across tenants.
        """
        for tenant_key, product_id in ((_TENANT_A, "prod-aaa"), (_TENANT_B, "prod-bbb")):
            service = _make_service(tenant_key=tenant_key)
            mock_product = Mock()
            mock_product.id = product_id

            with (
                patch.object(service, "list_projects", new_callable=AsyncMock, return_value=[]),
                patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
                patch.object(service, "_build_mcp_project_list", new_callable=AsyncMock, return_value=[]),
            ):
                mock_product_svc.return_value.get_active_product = AsyncMock(return_value=mock_product)
                result = await service.list_projects_for_mcp(
                    summary_only=True,
                    tenant_key=tenant_key,
                )

            assert result["product_id"] == product_id
            assert "project_types" not in result


class TestGetValidProjectTypesHelperRetained:
    """_get_valid_project_types must still exist and return a list.

    update_project_metadata_for_mcp depends on this helper to format the
    "Valid types: ..." validation error message when an unknown project_type
    is supplied. If the helper were accidentally removed in commit
    6f702526a, that error path would crash with AttributeError instead of
    raising a helpful ValidationError.
    """

    @pytest.mark.asyncio
    async def test_helper_still_callable_and_returns_list(self):
        service = _make_service(tenant_key=_TENANT_A)

        # Simulate the helper's downstream calls via patching at the import site
        # used inside the helper (giljo_mcp.services.taxonomy_ops).
        fake_type = Mock()
        fake_type.abbreviation = "AAA"
        fake_type.label = "Alpha"
        fake_type.color = "#123456"

        with (
            patch(
                "giljo_mcp.services.taxonomy_ops.ensure_default_types_seeded",
                new_callable=AsyncMock,
            ),
            patch(
                "giljo_mcp.services.taxonomy_ops.list_taxonomy_types",
                new_callable=AsyncMock,
                return_value=[fake_type],
            ),
        ):
            result = await service._get_valid_project_types(_TENANT_A)

        assert isinstance(result, list)
        assert result == [{"abbreviation": "AAA", "label": "Alpha", "color": "#123456"}]

    def test_helper_attribute_exists_on_service(self):
        """Static guard: the method symbol must remain on ProjectService."""
        assert hasattr(ProjectService, "_get_valid_project_types"), (
            "_get_valid_project_types must remain on ProjectService -- "
            "update_project_metadata_for_mcp depends on it for validation error messages."
        )
