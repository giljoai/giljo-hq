# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

import pytest

from api.endpoints.projects.models import ProjectResponse


def _make_min_response(**overrides):
    base = {
        "id": "proj-0036",
        "alias": "",
        "name": "CE-0036 Regression Project",
        "mission": "ensure implementation_launched_at flows through REST",
        "status": "active",
        "created_at": "2026-05-18T00:00:00+00:00",
        "updated_at": "2026-05-18T01:00:00+00:00",
        "agent_count": 0,
        "message_count": 0,
    }
    base.update(overrides)
    return ProjectResponse(**base)


def test_project_response_implementation_launched_at_defaults_to_none():
    r = _make_min_response()
    assert r.implementation_launched_at is None


def test_project_response_implementation_launched_at_accepts_datetime():
    ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    r = _make_min_response(implementation_launched_at=ts)
    assert r.implementation_launched_at == ts


def test_project_response_serializes_implementation_launched_at():
    ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    r = _make_min_response(implementation_launched_at=ts)
    data = r.model_dump()
    assert "implementation_launched_at" in data
    assert data["implementation_launched_at"] == ts


def test_project_response_serializes_field_even_when_none():
    r = _make_min_response()
    data = r.model_dump()
    assert "implementation_launched_at" in data
    assert data["implementation_launched_at"] is None


@pytest.mark.parametrize("staging_status", ["staging", "staging_complete", None])
def test_project_response_field_is_independent_of_staging_status(staging_status):
    ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    r = _make_min_response(staging_status=staging_status, implementation_launched_at=ts)
    assert r.staging_status == staging_status
    assert r.implementation_launched_at == ts
