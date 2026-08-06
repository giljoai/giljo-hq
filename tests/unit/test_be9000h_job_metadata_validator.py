# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression tests for BE-9000h — job_metadata write-boundary validation.

The bug class: ``agent_jobs.job_metadata`` had a Pydantic validator that was
NEVER called at any write site, and its fields were stale. An agent-supplied
``current_step`` (via report_progress) flowed into the JSONB column with no
length cap.

These tests pin the fix at the layer the bug occurred (the ProgressService
report_progress path) AND at the validator itself:
- an oversize ``current_step`` is REJECTED (not stored raw) through the real
  ``report_progress`` entrypoint;
- a normal ``current_step`` still round-trips into ``job_metadata`` (the
  load-bearing happy path — the validator must not break legitimate writes).
"""

import sys
import types
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.exceptions import ValidationError as GiljoValidationError


# Stub the api package so that api/__init__.py is never executed during
# collection (mirrors the sibling progress-service unit tests).
if "api" not in sys.modules:
    _api_stub = types.ModuleType("api")
    _api_stub.__path__ = ["api"]
    _api_stub.__package__ = "api"
    sys.modules["api"] = _api_stub

from giljo_mcp.models import AgentJob  # noqa: E402
from giljo_mcp.schemas.jsonb_validators import (  # noqa: E402
    _JOB_METADATA_CURRENT_STEP_MAX,
    validate_agent_job_metadata,
)
from giljo_mcp.services.progress_service import ProgressService  # noqa: E402


# --- Validator unit tests (the schema boundary) ---------------------------


class TestValidateAgentJobMetadata:
    def test_none_passthrough(self):
        assert validate_agent_job_metadata(None) is None

    def test_typical_payload_returned_unchanged(self):
        data = {
            "field_toggles": {"a": True},
            "depth_config": {"depth": "light"},
            "user_id": str(uuid.uuid4()),
            "tool": "claude",
            "created_via": "thin_client_spawn",
            "todo_steps": {"total_steps": 5, "completed_steps": 3, "skipped_steps": 0, "current_step": "step 3"},
        }
        # Returned object is the SAME dict (no reshaping / null-padding).
        assert validate_agent_job_metadata(data) is data

    def test_extra_keys_allowed(self):
        data = {"chain_conductor": True, "run_id": "r", "reused_at": "2026-01-01", "thin_client": True}
        assert validate_agent_job_metadata(data) is data

    def test_non_dict_rejected(self):
        with pytest.raises(TypeError):
            validate_agent_job_metadata(["not", "a", "dict"])

    def test_oversize_current_step_rejected(self):
        from pydantic import ValidationError as PydanticValidationError

        oversize = "x" * (_JOB_METADATA_CURRENT_STEP_MAX + 1)
        with pytest.raises(PydanticValidationError):
            validate_agent_job_metadata({"todo_steps": {"current_step": oversize}})

    def test_oversize_tool_rejected(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            validate_agent_job_metadata({"tool": "x" * 201})


# --- ProgressService report_progress path (the failing layer) -------------


def _make_service() -> ProgressService:
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value="test-tenant")
    return ProgressService(db_manager=Mock(), tenant_manager=tenant_manager, websocket_manager=None)


class _FakeSessionCtx:
    """Minimal async-context-manager wrapping a mock session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _wire_session(service, monkeypatch, job):
    """Patch report_progress's session + fetch helpers to in-memory mocks."""
    session = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target
    execution = Mock()
    execution.status = "working"
    execution.progress = 0
    execution.current_task = None
    execution.last_progress_at = None
    execution.agent_id = uuid.uuid4()

    monkeypatch.setattr(service, "_get_session", lambda tenant_key=None: _FakeSessionCtx(session))
    monkeypatch.setattr(service, "_fetch_active_execution", AsyncMock(return_value=execution))
    monkeypatch.setattr(service, "_fetch_job", AsyncMock(return_value=job))
    return session


@pytest.mark.asyncio
async def test_report_progress_rejects_oversize_current_step(monkeypatch):
    """An oversize current_step is rejected at the boundary and NOT stored raw."""
    service = _make_service()
    job = AgentJob(job_id=str(uuid.uuid4()), tenant_key="test-tenant", job_metadata={})
    job.project_id = uuid.uuid4()
    _wire_session(service, monkeypatch, job)

    oversize = "x" * (_JOB_METADATA_CURRENT_STEP_MAX + 500)
    with pytest.raises(GiljoValidationError):
        await service.report_progress(
            job_id=job.job_id,
            progress={"mode": "todo", "total_steps": 3, "completed_steps": 1, "current_step": oversize},
            tenant_key="test-tenant",
        )

    # The raw oversize value never reached the column.
    assert job.job_metadata == {}


@pytest.mark.asyncio
async def test_process_todo_items_stores_valid_current_step(monkeypatch):
    """A normal current_step still round-trips into job_metadata (happy path)."""
    service = _make_service()
    job = AgentJob(job_id=str(uuid.uuid4()), tenant_key="test-tenant", job_metadata={})
    session = AsyncMock()
    session.info = {}  # tenant_session_context save/restore target

    await service._process_todo_items(
        session=session,
        job=job,
        job_id=job.job_id,
        tenant_key="test-tenant",
        progress={"mode": "todo", "total_steps": 4, "completed_steps": 2, "current_step": "Running migrations"},
        todo_append=None,
    )

    assert job.job_metadata["todo_steps"]["current_step"] == "Running migrations"
    assert job.job_metadata["todo_steps"]["total_steps"] == 4
    assert job.job_metadata["todo_steps"]["completed_steps"] == 2
