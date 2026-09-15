# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from giljo_mcp.exceptions import ProjectStateError, ValidationError
from giljo_mcp.schemas.service_responses import ProjectData
from giljo_mcp.services.project_service import ProjectService


@pytest.fixture
def project_service():
    db_manager = Mock()
    tenant_manager = Mock()
    return ProjectService(db_manager, tenant_manager)


@pytest.fixture
def mock_project():
    project = Mock()
    project.id = "proj-001"
    project.name = "Original Name"
    project.status = "active"
    project.mission = None
    project.description = "Original Description"
    project.execution_mode = "orchestrated"
    project.cancellation_reason = None
    project.early_termination = False
    project.auto_checkin_enabled = False
    project.auto_checkin_interval = 10
    project.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    project.updated_at = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
    project.completed_at = None
    project.implementation_launched_at = None
    project.product_id = "product-001"
    project.project_type_id = "type-001"
    project_type_mock = Mock()
    project_type_mock.id = "type-001"
    project_type_mock.abbreviation = "FT"
    project_type_mock.label = "Feature"
    project_type_mock.color = "#FF0000"
    project.project_type = project_type_mock
    project.series_number = 42
    project.subseries = "a"
    project.taxonomy_alias = "0042a"
    project.successor_project_id = None
    return project


class TestApplyProjectUpdates:

    def test_applies_allowed_name_field(self, project_service, mock_project):
        project_service._apply_project_updates(mock_project, {"name": "New Name"})
        assert mock_project.name == "New Name"

    def test_applies_allowed_description_field(self, project_service, mock_project):
        project_service._apply_project_updates(mock_project, {"description": "New Desc"})
        assert mock_project.description == "New Desc"

    def test_applies_allowed_mission_field(self, project_service, mock_project):
        project_service._apply_project_updates(mock_project, {"mission": "New Mission"})
        assert mock_project.mission == "New Mission"

    def test_applies_allowed_status_field(self, project_service, mock_project):
        project_service._apply_project_updates(mock_project, {"status": "completed"})
        assert mock_project.status == "completed"

    def test_applies_multiple_fields(self, project_service, mock_project):
        project_service._apply_project_updates(
            mock_project,
            {
                "name": "Updated",
                "description": "Updated Desc",
                "series_number": 99,
            },
        )
        assert mock_project.name == "Updated"
        assert mock_project.description == "Updated Desc"
        assert mock_project.series_number == 99

    def test_ignores_disallowed_fields(self, project_service, mock_project):
        original_id = mock_project.id
        project_service._apply_project_updates(mock_project, {"id": "hacked-id", "name": "Valid"})
        assert mock_project.id == original_id
        assert mock_project.name == "Valid"

    def test_sets_updated_at_timestamp(self, project_service, mock_project):
        before = datetime.now(UTC)
        project_service._apply_project_updates(mock_project, {"name": "Updated"})
        after = datetime.now(UTC)
        assert before <= mock_project.updated_at <= after

    def test_raises_on_execution_mode_change_after_launch(self, project_service, mock_project):
        mock_project.implementation_launched_at = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ProjectStateError):
            project_service._apply_project_updates(mock_project, {"execution_mode": "claude_code_cli"})

    def test_allows_execution_mode_change_when_staged_but_not_launched(self, project_service, mock_project):
        mock_project.mission = "Orchestrator-generated mission"
        mock_project.implementation_launched_at = None
        project_service._apply_project_updates(mock_project, {"execution_mode": "claude_code_cli"})
        assert mock_project.execution_mode == "claude_code_cli"

    def test_allows_execution_mode_change_when_no_mission(self, project_service, mock_project):
        mock_project.mission = None
        project_service._apply_project_updates(mock_project, {"execution_mode": "claude_code_cli"})
        assert mock_project.execution_mode == "claude_code_cli"

    def test_allows_execution_mode_change_when_mission_empty(self, project_service, mock_project):
        mock_project.mission = "   "
        project_service._apply_project_updates(mock_project, {"execution_mode": "claude_code_cli"})
        assert mock_project.execution_mode == "claude_code_cli"

    def test_all_allowed_fields_are_accepted(self, project_service, mock_project):
        updates = {
            "name": "N",
            "description": "D",
            "mission": "M",
            "execution_mode": "claude_code_cli",
            "status": "completed",
            "completed_at": datetime(2026, 3, 1, tzinfo=UTC),
            "project_type_id": "type-new",
            "series_number": 100,
            "subseries": "b",
        }
        mock_project.mission = None
        project_service._apply_project_updates(mock_project, updates)
        assert mock_project.name == "N"
        assert mock_project.description == "D"
        assert mock_project.mission == "M"
        assert mock_project.execution_mode == "claude_code_cli"
        assert mock_project.status == "completed"
        assert mock_project.completed_at == datetime(2026, 3, 1, tzinfo=UTC)
        assert mock_project.project_type_id == "type-new"
        assert mock_project.series_number == 100
        assert mock_project.subseries == "b"

    def test_rejects_none_execution_mode(self, project_service, mock_project):
        mock_project.mission = None
        with pytest.raises(ValidationError) as exc:
            project_service._apply_project_updates(mock_project, {"execution_mode": None})
        assert "execution_mode" in str(exc.value).lower()

    def test_rejects_unknown_execution_mode(self, project_service, mock_project):
        mock_project.mission = None
        with pytest.raises(ValidationError):
            project_service._apply_project_updates(mock_project, {"execution_mode": "definitely_not_a_mode"})

    def test_omitted_execution_mode_skips_validation(self, project_service, mock_project):
        mock_project.mission = None
        project_service._apply_project_updates(mock_project, {"name": "Renamed"})
        assert mock_project.name == "Renamed"


class TestBuildProjectData:

    def test_returns_project_data_instance(self, mock_project):
        result = ProjectService._build_project_data(mock_project)
        assert isinstance(result, ProjectData)

    def test_maps_all_direct_fields(self, mock_project):
        result = ProjectService._build_project_data(mock_project)
        assert result.id == "proj-001"
        assert result.name == "Original Name"
        assert result.status == "active"
        assert result.mission is None
        assert result.description == "Original Description"
        assert result.execution_mode == "orchestrated"
        assert result.product_id == "product-001"
        assert result.project_type_id == "type-001"
        assert result.series_number == 42
        assert result.subseries == "a"
        assert result.taxonomy_alias == "0042a"

    def test_formats_datetime_fields_as_isoformat(self, mock_project):
        result = ProjectService._build_project_data(mock_project)
        assert result.created_at == "2026-01-01T12:00:00+00:00"
        assert result.updated_at == "2026-01-02T12:00:00+00:00"

    def test_handles_none_datetime_fields(self, mock_project):
        mock_project.created_at = None
        mock_project.updated_at = None
        mock_project.completed_at = None
        result = ProjectService._build_project_data(mock_project)
        assert result.created_at is None
        assert result.updated_at is None
        assert result.completed_at is None

    def test_cancellation_reason_defaults_to_none(self, mock_project):
        result = ProjectService._build_project_data(mock_project)
        assert result.cancellation_reason is None

    def test_cancellation_reason_preserved_when_set(self, mock_project):
        mock_project.cancellation_reason = "Budget exceeded"
        result = ProjectService._build_project_data(mock_project)
        assert result.cancellation_reason == "Budget exceeded"

    def test_early_termination_defaults_to_false(self, mock_project):
        result = ProjectService._build_project_data(mock_project)
        assert result.early_termination is False

    def test_early_termination_preserved_when_true(self, mock_project):
        mock_project.early_termination = True
        result = ProjectService._build_project_data(mock_project)
        assert result.early_termination is True

    def test_project_type_object_passed_through(self, mock_project):
        result = ProjectService._build_project_data(mock_project)
        assert result.project_type is not None
        assert result.project_type.label == "Feature"
        assert result.project_type.abbreviation == "FT"

    def test_completed_at_formatted_when_present(self, mock_project):
        mock_project.completed_at = datetime(2026, 3, 1, 15, 30, 0, tzinfo=UTC)
        result = ProjectService._build_project_data(mock_project)
        assert result.completed_at == "2026-03-01T15:30:00+00:00"
