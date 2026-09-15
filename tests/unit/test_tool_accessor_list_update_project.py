# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock, patch

import pytest

from giljo_mcp.tools.tool_accessor import ToolAccessor


_PRODUCT_SERVICE_PATH = "giljo_mcp.services.product_service.ProductService"




def _make_accessor(tenant_key: str = "tenant-test") -> ToolAccessor:
    db_manager = Mock()
    mock_session = AsyncMock()
    db_manager.get_session_async = Mock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.info = {}
    mock_result = Mock()
    mock_result.scalars = Mock(return_value=Mock(all=Mock(return_value=[])))
    mock_session.execute = AsyncMock(return_value=mock_result)
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
        test_session=mock_session,
    )


def _mock_project(
    project_id="proj-001",
    name="Test Project",
    description="A test project",
    status="active",
    product_id="prod-001",
    project_type_id=None,
    series_number=None,
    taxonomy_alias=None,
    created_at=None,
    updated_at=None,
):
    proj = Mock()
    proj.id = project_id
    proj.name = name
    proj.description = description
    proj.status = status
    proj.product_id = product_id
    proj.project_type_id = project_type_id
    proj.series_number = series_number
    proj.taxonomy_alias = taxonomy_alias
    proj.created_at = created_at
    proj.updated_at = updated_at
    proj.mission = ""
    proj.execution_mode = "parallel"
    proj.auto_checkin_enabled = False
    proj.auto_checkin_interval = 15
    proj.cancellation_reason = None
    proj.early_termination = False
    proj.completed_at = None
    proj.project_type = None
    proj.subseries = None
    proj.staging_status = None
    proj.tenant_key = "tenant-test"
    return proj


def _patch_active_product(product_id="prod-001"):
    mock_product = Mock()
    mock_product.id = product_id

    p = patch(_PRODUCT_SERVICE_PATH)
    return p, mock_product






class TestListProjectsBehavior:

    @pytest.mark.asyncio
    async def test_returns_projects_for_active_product(self):
        accessor = _make_accessor()

        mock_product = Mock()
        mock_product.id = "prod-001"

        mock_list_item = Mock()
        mock_list_item.id = "proj-001"
        mock_list_item.name = "Test Project"
        mock_list_item.description = "A test project description that is long"
        mock_list_item.status = "active"
        mock_list_item.product_id = "prod-001"
        mock_list_item.project_type_id = None
        mock_list_item.series_number = None
        mock_list_item.taxonomy_alias = None
        mock_list_item.created_at = "2026-04-13T00:00:00"

        built_project = {"project_id": "proj-001", "name": "Test Project", "status": "active"}

        with (
            patch.object(
                accessor._project_service,
                "list_projects",
                new_callable=AsyncMock,
                return_value=[mock_list_item],
            ),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
            patch.object(
                accessor._project_service,
                "_build_mcp_project_list",
                new_callable=AsyncMock,
                return_value=[built_project],
            ),
            patch.object(
                accessor._project_service, "_get_valid_project_types", new_callable=AsyncMock, return_value=[]
            ),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_product,
            )
            mock_product_svc.return_value.resolve_binding_product = AsyncMock(return_value=mock_product)
            result = await accessor._project_service.list_projects_for_mcp(tenant_key="tenant-test")

        assert result["success"] is True
        assert len(result["projects"]) == 1
        assert result["projects"][0]["project_id"] == "proj-001"
        assert result["projects"][0]["name"] == "Test Project"

    @pytest.mark.asyncio
    async def test_passes_status_filter_to_service(self):
        accessor = _make_accessor()

        mock_product = Mock()
        mock_product.id = "prod-001"

        active_proj = Mock()
        active_proj.id = "p-active"
        active_proj.product_id = "prod-001"
        active_proj.status = "active"
        active_proj.hidden = False
        active_proj.project_type = None
        active_proj.taxonomy_alias = "AAA"
        active_proj.created_at = "2026-01-01T00:00:00+00:00"
        active_proj.completed_at = None

        inactive_proj = Mock()
        inactive_proj.id = "p-inactive"
        inactive_proj.product_id = "prod-001"
        inactive_proj.status = "inactive"
        inactive_proj.hidden = False
        inactive_proj.project_type = None
        inactive_proj.taxonomy_alias = "BBB"
        inactive_proj.created_at = "2026-01-01T00:00:00+00:00"
        inactive_proj.completed_at = None

        captured: list = []

        async def fake_build(projects, depth, tk, **_kwargs):
            captured.extend(projects)
            return [{"project_id": p.id, "status": p.status} for p in projects]

        async def _fake_list_projects(*_args, **kwargs):
            st = kwargs.get("status")
            rows = [active_proj, inactive_proj]
            if st is None:
                return rows
            allowed = {st} if isinstance(st, str) else set(st)
            return [r for r in rows if r.status in allowed]

        with (
            patch.object(
                accessor._project_service,
                "list_projects",
                new=AsyncMock(side_effect=_fake_list_projects),
            ),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
            patch.object(accessor._project_service, "_build_mcp_project_list", new=AsyncMock(side_effect=fake_build)),
            patch.object(
                accessor._project_service, "_get_valid_project_types", new_callable=AsyncMock, return_value=[]
            ),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_product,
            )
            mock_product_svc.return_value.resolve_binding_product = AsyncMock(return_value=mock_product)
            result = await accessor._project_service.list_projects_for_mcp(
                status_filter="active",
                tenant_key="tenant-test",
            )

        ids = {row["project_id"] for row in result["projects"]}
        assert ids == {"p-active"}, "status_filter='active' must yield only active rows"

    @pytest.mark.asyncio
    async def test_status_filter_all_passes_none(self):
        accessor = _make_accessor()

        mock_product = Mock()
        mock_product.id = "prod-001"

        active_proj = Mock()
        active_proj.id = "p-active"
        active_proj.product_id = "prod-001"
        active_proj.status = "active"
        active_proj.hidden = False
        active_proj.project_type = None
        active_proj.taxonomy_alias = "AAA"
        active_proj.created_at = "2026-01-01T00:00:00+00:00"
        active_proj.completed_at = None

        completed_proj = Mock()
        completed_proj.id = "p-completed"
        completed_proj.product_id = "prod-001"
        completed_proj.status = "completed"
        completed_proj.hidden = False
        completed_proj.project_type = None
        completed_proj.taxonomy_alias = "BBB"
        completed_proj.created_at = "2026-01-01T00:00:00+00:00"
        completed_proj.completed_at = "2026-01-02T00:00:00+00:00"

        async def fake_build(projects, depth, tk, **_kwargs):
            return [{"project_id": p.id, "status": p.status} for p in projects]

        with (
            patch.object(
                accessor._project_service,
                "list_projects",
                new_callable=AsyncMock,
                return_value=[active_proj, completed_proj],
            ),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
            patch.object(accessor._project_service, "_build_mcp_project_list", new=AsyncMock(side_effect=fake_build)),
            patch.object(
                accessor._project_service, "_get_valid_project_types", new_callable=AsyncMock, return_value=[]
            ),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_product,
            )
            mock_product_svc.return_value.resolve_binding_product = AsyncMock(return_value=mock_product)
            result = await accessor._project_service.list_projects_for_mcp(
                status_filter="all",
                tenant_key="tenant-test",
            )

        ids = {row["project_id"] for row in result["projects"]}
        assert ids == {"p-active", "p-completed"}, (
            "status_filter='all' must include archived projects (legacy contract preserved)"
        )

    @pytest.mark.asyncio
    async def test_raises_on_no_active_product(self):
        accessor = _make_accessor()

        from giljo_mcp.exceptions import ValidationError

        with patch(_PRODUCT_SERVICE_PATH) as mock_product_svc:
            mock_product_svc.return_value.get_default_product = AsyncMock(return_value=None)
            mock_product_svc.return_value.resolve_binding_product = AsyncMock(
                side_effect=ValidationError("No active product set. Please activate a product first.")
            )

            with pytest.raises(Exception, match="No active product"):
                await accessor._project_service.list_projects_for_mcp(tenant_key="tenant-test")

    @pytest.mark.asyncio
    async def test_description_returned_in_full(self):
        accessor = _make_accessor()

        mock_product = Mock()
        mock_product.id = "prod-001"

        long_desc = "A" * 300
        mock_list_item = Mock()
        mock_list_item.id = "proj-001"
        mock_list_item.name = "Long Desc"
        mock_list_item.description = long_desc
        mock_list_item.status = "active"
        mock_list_item.product_id = "prod-001"
        mock_list_item.project_type_id = None
        mock_list_item.series_number = None
        mock_list_item.taxonomy_alias = None
        mock_list_item.created_at = "2026-04-13T00:00:00"

        long_project = {"project_id": "proj-001", "name": "Long Desc", "description": long_desc}

        with (
            patch.object(
                accessor._project_service,
                "list_projects",
                new_callable=AsyncMock,
                return_value=[mock_list_item],
            ),
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
            patch.object(
                accessor._project_service,
                "_build_mcp_project_list",
                new_callable=AsyncMock,
                return_value=[long_project],
            ),
            patch.object(
                accessor._project_service, "_get_valid_project_types", new_callable=AsyncMock, return_value=[]
            ),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_product,
            )
            mock_product_svc.return_value.resolve_binding_product = AsyncMock(return_value=mock_product)
            result = await accessor._project_service.list_projects_for_mcp(tenant_key="tenant-test")

        desc = result["projects"][0]["description"]
        assert desc == long_desc
        assert len(desc) == 300

    @pytest.mark.asyncio
    async def test_rejects_invalid_status_filter(self):
        accessor = _make_accessor()

        with pytest.raises(Exception, match=r"[Ii]nvalid.*status"):
            await accessor._project_service.list_projects_for_mcp(
                status_filter="bogus",
                tenant_key="tenant-test",
            )






class TestUpdateProjectMetadataBehavior:

    @pytest.mark.asyncio
    async def test_updates_name_successfully(self):
        accessor = _make_accessor()

        mock_project_data = Mock()
        mock_project_data.id = "proj-001"
        mock_project_data.name = "New Name"
        mock_project_data.description = "Desc"
        mock_project_data.status = "active"
        mock_project_data.product_id = "prod-001"
        mock_project_data.created_at = "2026-04-13T00:00:00"
        mock_project_data.updated_at = "2026-04-13T01:00:00"
        mock_project_data.taxonomy_alias = None
        mock_project_data.series_number = None
        mock_project_data.project_type_id = None

        mock_project_obj = _mock_project(product_id="prod-001")
        mock_active_product = Mock()
        mock_active_product.id = "prod-001"

        with (
            patch.object(
                accessor._project_service,
                "get_project",
                new_callable=AsyncMock,
                return_value=mock_project_obj,
            ),
            patch.object(
                accessor._project_service,
                "update_project",
                new_callable=AsyncMock,
                return_value=mock_project_data,
            ) as mock_update,
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_active_product,
            )
            result = await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                name="New Name",
                tenant_key="tenant-test",
            )

        assert result["success"] is True
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["updates"]["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_updates_description_and_status(self):
        accessor = _make_accessor()

        mock_project_data = Mock()
        mock_project_data.id = "proj-001"
        mock_project_data.name = "Test"
        mock_project_data.description = "Updated desc"
        mock_project_data.status = "completed"
        mock_project_data.product_id = "prod-001"
        mock_project_data.created_at = "2026-04-13T00:00:00"
        mock_project_data.updated_at = "2026-04-13T01:00:00"
        mock_project_data.taxonomy_alias = None
        mock_project_data.series_number = None
        mock_project_data.project_type_id = None

        mock_project_obj = _mock_project(product_id="prod-001")
        mock_active_product = Mock()
        mock_active_product.id = "prod-001"

        with (
            patch.object(
                accessor._project_service,
                "get_project",
                new_callable=AsyncMock,
                return_value=mock_project_obj,
            ),
            patch.object(
                accessor._project_service,
                "update_project",
                new_callable=AsyncMock,
                return_value=mock_project_data,
            ) as mock_update,
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_active_product,
            )
            result = await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                description="Updated desc",
                status="completed",
                tenant_key="tenant-test",
            )

        assert result["success"] is True
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["updates"]["description"] == "Updated desc"
        assert call_kwargs["updates"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_rejects_invalid_status_value(self):
        accessor = _make_accessor()

        with pytest.raises(Exception, match=r"[Ii]nvalid.*status"):
            await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                status="bogus",
                tenant_key="tenant-test",
            )

    @pytest.mark.asyncio
    async def test_rejects_name_exceeding_max_length(self):
        accessor = _make_accessor()

        with pytest.raises(Exception, match=r"[Nn]ame.*200|too long|exceed"):
            await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                name="X" * 201,
                tenant_key="tenant-test",
            )

    @pytest.mark.asyncio
    async def test_rejects_description_exceeding_max_length(self):
        accessor = _make_accessor()

        with pytest.raises(Exception, match=r"[Dd]escription.*20000|too long|exceed"):
            await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                description="Y" * 20001,
                tenant_key="tenant-test",
            )

    @pytest.mark.asyncio
    async def test_rejects_empty_project_id(self):
        accessor = _make_accessor()

        with pytest.raises(Exception, match=r"[Pp]roject.*required|[Pp]roject.*empty"):
            await accessor._project_service.update_project_metadata_for_mcp(
                project_id="  ",
                tenant_key="tenant-test",
            )

    @pytest.mark.asyncio
    async def test_rejects_no_fields_provided(self):
        accessor = _make_accessor()

        with pytest.raises(Exception, match=r"[Aa]t least one"):
            await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                tenant_key="tenant-test",
            )

    @pytest.mark.asyncio
    async def test_updates_a_project_belonging_to_a_non_active_product(self):
        accessor = _make_accessor()

        mock_project_data = Mock()
        mock_project_data.id = "proj-001"
        mock_project_data.name = "New Name"
        mock_project_data.description = "Desc"
        mock_project_data.status = "active"
        mock_project_data.product_id = "prod-OTHER"
        mock_project_data.created_at = "2026-04-13T00:00:00"
        mock_project_data.updated_at = "2026-04-13T01:00:00"
        mock_project_data.taxonomy_alias = None
        mock_project_data.series_number = None
        mock_project_data.project_type_id = None

        mock_project_obj = _mock_project(product_id="prod-OTHER")
        mock_active_product = Mock()
        mock_active_product.id = "prod-001"

        with (
            patch.object(
                accessor._project_service,
                "get_project",
                new_callable=AsyncMock,
                return_value=mock_project_obj,
            ),
            patch.object(
                accessor._project_service,
                "update_project",
                new_callable=AsyncMock,
                return_value=mock_project_data,
            ) as mock_update,
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_active_product,
            )
            result = await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                name="New Name",
                tenant_key="tenant-test",
            )

        assert result["success"] is True
        mock_update.assert_called_once()
        assert mock_update.call_args[1]["updates"]["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_only_provided_fields_in_updates(self):
        accessor = _make_accessor()

        mock_project_data = Mock()
        mock_project_data.id = "proj-001"
        mock_project_data.name = "Just Name"
        mock_project_data.description = "Orig"
        mock_project_data.status = "active"
        mock_project_data.product_id = "prod-001"
        mock_project_data.created_at = "2026-04-13T00:00:00"
        mock_project_data.updated_at = "2026-04-13T01:00:00"
        mock_project_data.taxonomy_alias = None
        mock_project_data.series_number = None
        mock_project_data.project_type_id = None

        mock_project_obj = _mock_project(product_id="prod-001")
        mock_active_product = Mock()
        mock_active_product.id = "prod-001"

        with (
            patch.object(
                accessor._project_service,
                "get_project",
                new_callable=AsyncMock,
                return_value=mock_project_obj,
            ),
            patch.object(
                accessor._project_service,
                "update_project",
                new_callable=AsyncMock,
                return_value=mock_project_data,
            ) as mock_update,
            patch(_PRODUCT_SERVICE_PATH) as mock_product_svc,
            patch.object(accessor._project_service, "board_counts", new_callable=AsyncMock, return_value=[]),
        ):
            mock_product_svc.return_value.get_default_product = AsyncMock(
                return_value=mock_active_product,
            )
            await accessor._project_service.update_project_metadata_for_mcp(
                project_id="proj-001",
                name="Just Name",
                tenant_key="tenant-test",
            )

        call_kwargs = mock_update.call_args[1]
        assert "name" in call_kwargs["updates"]
        assert "description" not in call_kwargs["updates"]
        assert "status" not in call_kwargs["updates"]
