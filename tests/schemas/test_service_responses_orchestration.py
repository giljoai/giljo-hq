# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.service_responses import (
    AuthResult,
    ConsolidationResult,
    InstructionsResponse,
    MissionResponse,
    MissionUpdateResult,
    SetupState,
    SpawnResult,
)




class TestSpawnResult:

    def test_creation_with_required_fields(self):
        result = SpawnResult(
            job_id="job-1",
            agent_id="agent-1",
            agent_prompt="Your mission prompt",
        )
        assert result.job_id == "job-1"
        assert result.agent_id == "agent-1"
        assert result.agent_prompt == "Your mission prompt"
        assert result.thin_client is True
        assert result.mission_stored is True

    def test_creation_with_all_fields(self):
        result = SpawnResult(
            job_id="job-2",
            agent_id="agent-2",
            execution_id="exec-2",
            agent_prompt="Prompt here",
            mission_stored=True,
            thin_client=True,
            thin_client_note=["Note 1", "Note 2"],
        )
        assert result.execution_id == "exec-2"
        assert result.mission_stored is True
        assert len(result.thin_client_note) == 2

    def test_no_token_fields(self):
        result = SpawnResult(job_id="j", agent_id="a", agent_prompt="p")
        assert not hasattr(result, "prompt_tokens") or "prompt_tokens" not in result.model_fields
        assert not hasattr(result, "mission_tokens") or "mission_tokens" not in result.model_fields
        assert not hasattr(result, "total_tokens") or "total_tokens" not in result.model_fields

    def test_missing_job_id_raises(self):
        with pytest.raises(ValidationError):
            SpawnResult(agent_id="a1", agent_prompt="p")

    def test_missing_agent_id_raises(self):
        with pytest.raises(ValidationError):
            SpawnResult(job_id="j1", agent_prompt="p")

    def test_missing_agent_prompt_raises(self):
        with pytest.raises(ValidationError):
            SpawnResult(job_id="j1", agent_id="a1")

    def test_model_dump(self):
        result = SpawnResult(job_id="j", agent_id="a", agent_prompt="p")
        dumped = result.model_dump()
        assert dumped["job_id"] == "j"
        assert dumped["agent_id"] == "a"
        assert dumped["thin_client"] is True

    def test_thin_client_note_default_factory_isolation(self):
        r1 = SpawnResult(job_id="j1", agent_id="a1", agent_prompt="p1")
        r2 = SpawnResult(job_id="j2", agent_id="a2", agent_prompt="p2")
        r1.thin_client_note.append("x")
        assert "x" not in r2.thin_client_note

    def test_from_attributes_config(self):
        assert SpawnResult.model_config.get("from_attributes") is True


class TestMissionResponse:

    def test_creation_with_required_fields(self):
        result = MissionResponse(job_id="job-1")
        assert result.job_id == "job-1"
        assert result.mission is None
        assert result.full_protocol is None
        assert result.agent_id is None
        assert result.blocked is False

    def test_creation_with_all_fields(self):
        result = MissionResponse(
            job_id="job-2",
            agent_id="agent-2",
            agent_name="impl-1",
            agent_display_name="implementer",
            agent_identity="You are IMPLEMENTER. Your expertise...",
            mission="Build feature X",
            project_id="proj-1",
            parent_job_id="parent-1",
            status="working",
            created_at="2026-01-01T00:00:00Z",
            started_at="2026-01-01T00:01:00Z",
            thin_client=True,
            full_protocol="Phase 1: ...\nPhase 2: ...",
            blocked=False,
            error=None,
            user_instruction=None,
        )
        assert result.full_protocol is not None
        assert result.agent_display_name == "implementer"
        assert result.agent_identity is not None

    def test_no_estimated_tokens_field(self):
        assert "estimated_tokens" not in MissionResponse.model_fields

    def test_agent_identity_optional(self):
        result = MissionResponse(job_id="j")
        assert result.agent_identity is None

    def test_missing_job_id_raises(self):
        with pytest.raises(ValidationError):
            MissionResponse(mission="Do something")

    def test_blocked_response(self):
        result = MissionResponse(
            job_id="j1",
            blocked=True,
            error="BLOCKED: Implementation not launched",
            user_instruction="Click Implement button",
        )
        assert result.blocked is True
        assert result.mission is None
        assert "BLOCKED" in result.error

    def test_model_dump(self):
        result = MissionResponse(job_id="j", mission="m")
        dumped = result.model_dump()
        assert dumped["job_id"] == "j"
        assert dumped["mission"] == "m"
        assert dumped["full_protocol"] is None
        assert dumped["blocked"] is False

    def test_from_attributes_config(self):
        assert MissionResponse.model_config.get("from_attributes") is True


class TestMissionUpdateResult:

    def test_creation_with_required_fields(self):
        result = MissionUpdateResult(job_id="job-1")
        assert result.job_id == "job-1"
        assert result.mission_updated is True
        assert result.mission_length == 0

    def test_creation_with_explicit_false(self):
        result = MissionUpdateResult(job_id="job-2", mission_updated=False)
        assert result.mission_updated is False

    def test_creation_with_mission_length(self):
        result = MissionUpdateResult(job_id="j1", mission_length=1500)
        assert result.mission_length == 1500

    def test_missing_job_id_raises(self):
        with pytest.raises(ValidationError):
            MissionUpdateResult()

    def test_model_dump(self):
        result = MissionUpdateResult(job_id="j")
        dumped = result.model_dump()
        assert dumped == {"job_id": "j", "mission_updated": True, "mission_length": 0}

    def test_from_attributes_config(self):
        assert MissionUpdateResult.model_config.get("from_attributes") is True


class TestInstructionsResponse:

    def test_is_alias_for_succession_context_result(self):
        from giljo_mcp.schemas.service_responses import SuccessionContextResult

        assert InstructionsResponse is SuccessionContextResult

    def test_creation_with_required_fields(self):
        result = InstructionsResponse(
            job_id="job-1",
            agent_id="agent-1",
        )
        assert result.job_id == "job-1"
        assert result.agent_id == "agent-1"
        assert result.context_reset is True

    def test_model_dump(self):
        result = InstructionsResponse(job_id="j", agent_id="a")
        dumped = result.model_dump()
        assert dumped["job_id"] == "j"
        assert dumped["agent_id"] == "a"

    def test_from_attributes_config(self):
        assert InstructionsResponse.model_config.get("from_attributes") is True




class TestConsolidationResult:

    def test_creation_defaults(self):
        result = ConsolidationResult()
        assert result.hash == ""
        assert result.source_docs == []
        assert result.light is not None
        assert result.medium is not None

    def test_creation_with_all_fields(self):
        from giljo_mcp.schemas.service_responses import SummaryLevel

        result = ConsolidationResult(
            light=SummaryLevel(summary="Brief summary", tokens=100),
            medium=SummaryLevel(summary="Medium summary", tokens=500),
            hash="abc123",
            source_docs=["doc1.pdf", "doc2.md"],
        )
        assert result.light.summary == "Brief summary"
        assert result.medium.tokens == 500
        assert result.hash == "abc123"
        assert len(result.source_docs) == 2

    def test_source_docs_default_factory_isolation(self):
        r1 = ConsolidationResult()
        r2 = ConsolidationResult()
        r1.source_docs.append("doc.pdf")
        assert "doc.pdf" not in r2.source_docs

    def test_model_dump(self):
        result = ConsolidationResult(hash="h1")
        dumped = result.model_dump()
        assert dumped["hash"] == "h1"
        assert dumped["source_docs"] == []

    def test_from_attributes_config(self):
        assert ConsolidationResult.model_config.get("from_attributes") is True




class TestAuthResult:

    def test_creation_with_required_fields(self):
        result = AuthResult(
            user_id="user-1",
            username="admin",
            token="jwt-token-here",
            tenant_key="tenant-abc",
        )
        assert result.user_id == "user-1"
        assert result.username == "admin"
        assert result.token == "jwt-token-here"
        assert result.tenant_key == "tenant-abc"
        assert result.role == "user"
        assert result.email is None
        assert result.full_name is None
        assert result.is_active is True
        assert result.created_at is None
        assert result.last_login is None

    def test_creation_with_admin_role(self):
        result = AuthResult(
            user_id="u1",
            username="superadmin",
            token="t",
            tenant_key="tk",
            role="admin",
        )
        assert result.role == "admin"

    def test_creation_with_profile_fields(self):
        result = AuthResult(
            user_id="u1",
            username="admin",
            token="t",
            tenant_key="tk",
            email="admin@example.com",
            full_name="Admin User",
            is_active=True,
            created_at="2026-01-01T00:00:00+00:00",
            last_login="2026-02-11T12:00:00+00:00",
        )
        assert result.email == "admin@example.com"
        assert result.full_name == "Admin User"
        assert result.is_active is True
        assert result.created_at == "2026-01-01T00:00:00+00:00"
        assert result.last_login == "2026-02-11T12:00:00+00:00"

    def test_missing_user_id_raises(self):
        with pytest.raises(ValidationError):
            AuthResult(username="u", token="t", tenant_key="tk")

    def test_missing_username_raises(self):
        with pytest.raises(ValidationError):
            AuthResult(user_id="u1", token="t", tenant_key="tk")

    def test_missing_token_raises(self):
        with pytest.raises(ValidationError):
            AuthResult(user_id="u1", username="u", tenant_key="tk")

    def test_missing_tenant_key_raises(self):
        with pytest.raises(ValidationError):
            AuthResult(user_id="u1", username="u", token="t")

    def test_model_dump(self):
        result = AuthResult(user_id="u", username="n", token="t", tenant_key="k")
        dumped = result.model_dump()
        assert dumped["user_id"] == "u"
        assert dumped["username"] == "n"
        assert dumped["token"] == "t"
        assert dumped["tenant_key"] == "k"
        assert dumped["role"] == "user"
        assert dumped["email"] is None
        assert dumped["full_name"] is None
        assert dumped["is_active"] is True

    def test_from_attributes_config(self):
        assert AuthResult.model_config.get("from_attributes") is True


class TestSetupState:

    def test_creation_with_tenant_key(self):
        state = SetupState(tenant_key="test_tenant")
        assert state.first_admin_created is False
        assert state.database_initialized is False
        assert state.tenant_key == "test_tenant"

    def test_creation_fully_configured(self):
        state = SetupState(
            first_admin_created=True,
            database_initialized=True,
            tenant_key="test_tenant",
        )
        assert state.first_admin_created is True
        assert state.database_initialized is True
        assert state.tenant_key == "test_tenant"

    def test_partial_configuration(self):
        state = SetupState(database_initialized=True, tenant_key="tk")
        assert state.first_admin_created is False
        assert state.database_initialized is True
        assert state.tenant_key == "tk"

    def test_model_dump(self):
        state = SetupState(first_admin_created=True, tenant_key="tk")
        dumped = state.model_dump()
        assert dumped["first_admin_created"] is True
        assert dumped["database_initialized"] is False
        assert dumped["tenant_key"] == "tk"

    def test_from_attributes_config(self):
        assert SetupState.model_config.get("from_attributes") is True

    def test_missing_tenant_key_raises(self):
        with pytest.raises(ValidationError):
            SetupState()
