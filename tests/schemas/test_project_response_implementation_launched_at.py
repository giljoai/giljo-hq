# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CE-0036 regression test — ProjectResponse must expose implementation_launched_at.

The frontend's useProjectCloseout guard (useProjectCloseout.js:44-49) hides the
Close Project button when staging_status == 'staging_complete' AND
implementation_launched_at is missing/null. CE-0028b added the field to the
MCP-side response schemas but missed the REST schema at
api/endpoints/projects/models.py that the project page actually consumes.

The bug surfaced when an impl-end project on the test install couldn't be closed because
the API stripped implementation_launched_at from the project payload, even
though the DB column was populated. The fix: add the field to the REST
ProjectResponse and pass it through every construction site.
"""

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
    """Field must exist on the schema with a None default so legacy callers
    that don't pass it don't break."""
    r = _make_min_response()
    assert r.implementation_launched_at is None


def test_project_response_implementation_launched_at_accepts_datetime():
    """When the project has launched implementation, the field carries the
    timestamp through — this is what the frontend reads to evaluate the
    closeout-button gate."""
    ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    r = _make_min_response(implementation_launched_at=ts)
    assert r.implementation_launched_at == ts


def test_project_response_serializes_implementation_launched_at():
    """The serialized response must include the field so it actually reaches
    the frontend (not just exist on the Python schema)."""
    ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    r = _make_min_response(implementation_launched_at=ts)
    data = r.model_dump()
    assert "implementation_launched_at" in data
    assert data["implementation_launched_at"] == ts


def test_project_response_serializes_field_even_when_none():
    """Field must appear in serialized output even when null — the frontend
    checks for the property's presence; missing-key vs explicit-null have
    different falsy behavior in the JS gate."""
    r = _make_min_response()
    data = r.model_dump()
    assert "implementation_launched_at" in data
    assert data["implementation_launched_at"] is None


@pytest.mark.parametrize("staging_status", ["staging", "staging_complete", None])
def test_project_response_field_is_independent_of_staging_status(staging_status):
    """The two fields are independent — staging_status drives one part of the
    UI gate, implementation_launched_at drives another. Both must be
    serializable independently."""
    ts = datetime(2026, 5, 18, 3, 29, 18, tzinfo=UTC)
    r = _make_min_response(staging_status=staging_status, implementation_launched_at=ts)
    assert r.staging_status == staging_status
    assert r.implementation_launched_at == ts
