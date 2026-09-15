# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from api.endpoints.agent_jobs.models import JobResponse
from api.endpoints.agent_jobs.status import job_to_response




def _make_job_dict(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid4()),
        "job_id": str(uuid4()),
        "agent_id": str(uuid4()),
        "execution_id": str(uuid4()),
        "tenant_key": "test_tenant",
        "project_id": str(uuid4()),
        "agent_display_name": "implementer",
        "agent_name": "backend-implementer",
        "mission": "Test mission",
        "status": "active",
        "progress": 50,
        "created_at": datetime.now(tz=UTC),
    }
    base.update(overrides)
    return base




class TestMCPToolSchemaPhase:

    def test_phase_in_sdk_tool_registration(self):
        import inspect

        from api.endpoints.mcp_sdk_server import spawn_job

        sig = inspect.signature(spawn_job)
        assert "phase" in sig.parameters, "phase not in spawn_job SDK tool signature"

    def test_phase_type_is_optional_int(self):
        import inspect

        from api.endpoints.mcp_sdk_server import spawn_job

        sig = inspect.signature(spawn_job)
        param = sig.parameters["phase"]
        assert param.default is None, "phase should default to None"




class TestJobResponsePhaseField:

    def test_phase_field_exists_on_model(self):
        assert "phase" in JobResponse.model_fields

    def test_phase_defaults_to_none(self):
        response = JobResponse(
            id=str(uuid4()),
            job_id=str(uuid4()),
            tenant_key="test_tenant",
            agent_display_name="implementer",
            mission="Test",
            status="active",
            created_at=datetime.now(tz=UTC),
        )
        assert response.phase is None

    def test_phase_accepts_integer(self):
        response = JobResponse(
            id=str(uuid4()),
            job_id=str(uuid4()),
            tenant_key="test_tenant",
            agent_display_name="implementer",
            mission="Test",
            status="active",
            created_at=datetime.now(tz=UTC),
            phase=3,
        )
        assert response.phase == 3

    def test_phase_serialization(self):
        response = JobResponse(
            id=str(uuid4()),
            job_id=str(uuid4()),
            tenant_key="test_tenant",
            agent_display_name="implementer",
            mission="Test",
            status="active",
            created_at=datetime.now(tz=UTC),
            phase=1,
        )
        data = response.model_dump()
        assert data["phase"] == 1

    def test_phase_none_serialization(self):
        response = JobResponse(
            id=str(uuid4()),
            job_id=str(uuid4()),
            tenant_key="test_tenant",
            agent_display_name="implementer",
            mission="Test",
            status="active",
            created_at=datetime.now(tz=UTC),
        )
        data = response.model_dump()
        assert data["phase"] is None




class TestJobToResponsePhase:

    def test_phase_mapped_from_job_dict(self):
        job = _make_job_dict(phase=2)
        response = job_to_response(job)
        assert response.phase == 2

    def test_phase_none_when_not_in_job_dict(self):
        job = _make_job_dict()
        job.pop("phase", None)
        response = job_to_response(job)
        assert response.phase is None

    def test_phase_none_when_explicitly_none(self):
        job = _make_job_dict(phase=None)
        response = job_to_response(job)
        assert response.phase is None

    def test_phase_integer_values(self):
        for phase_val in [1, 2, 3, 5, 10]:
            job = _make_job_dict(phase=phase_val)
            response = job_to_response(job)
            assert response.phase == phase_val, f"Expected phase={phase_val}"
