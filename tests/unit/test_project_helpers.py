# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for project_helpers module (Sprint 002e extraction)."""

from unittest.mock import MagicMock

from giljo_mcp.services.project_helpers import _build_ws_project_data


def test_build_ws_project_data_returns_expected_fields():
    """_build_ws_project_data returns name, description, status, mission, product_id."""
    project = MagicMock()
    project.name = "Test"
    project.description = "Desc"
    project.status = "active"
    project.mission = "Mission text"
    project.product_id = "prod-1"  # BE-9518

    result = _build_ws_project_data(project)

    assert result == {
        "name": "Test",
        "description": "Desc",
        "status": "active",
        "mission": "Mission text",
        "product_id": "prod-1",  # BE-9518
    }


def test_build_ws_project_data_handles_none_fields():
    """_build_ws_project_data handles None values gracefully."""
    project = MagicMock()
    project.name = "P"
    project.description = None
    project.status = "inactive"
    project.mission = None

    result = _build_ws_project_data(project)

    assert result["description"] is None
    assert result["mission"] is None
