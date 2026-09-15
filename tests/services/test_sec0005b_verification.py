# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException

from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.system_prompts.service import SystemPromptService
from giljo_mcp.template_seeder import (
    _get_user_facing_orchestrator_seed,
    compose_orchestrator_identity,
    get_orchestrator_identity_content,
)




@pytest.mark.asyncio
class TestPropertyATenantIsolation:

    async def test_tenant_b_sees_default_when_only_tenant_a_has_override(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        tenant_a = "tk_sec5b_verify_iso_a"
        tenant_b = "tk_sec5b_verify_iso_b"

        await service.update_orchestrator_prompt(
            tenant_key=tenant_a,
            content="Tenant A custom prompt",
            updated_by="admin@a",
            session=db_session,
        )
        await db_session.commit()

        a_result = await service.get_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        b_result = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)

        assert a_result.is_override is True
        assert a_result.content == "Tenant A custom prompt"
        assert b_result.is_override is False
        assert "Tenant A custom prompt" not in b_result.content

    async def test_tenant_a_reset_does_not_touch_tenant_b(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        tenant_a = "tk_sec5b_verify_reset_a"
        tenant_b = "tk_sec5b_verify_reset_b"

        await service.update_orchestrator_prompt(
            tenant_key=tenant_a,
            content="A override",
            updated_by="admin@a",
            session=db_session,
        )
        await db_session.commit()

        b_before = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)

        await service.reset_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        await db_session.commit()

        a_after = await service.get_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        b_after = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)

        assert a_after.is_override is False
        assert b_after.is_override is False
        assert b_before.content == b_after.content




@pytest.mark.asyncio
class TestPropertyBTenantRequired:

    async def test_get_empty_string_raises(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.get_orchestrator_prompt(tenant_key="", session=db_session)

    async def test_get_none_raises(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.get_orchestrator_prompt(tenant_key=None, session=db_session)  # type: ignore[arg-type]

    async def test_update_none_raises(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.update_orchestrator_prompt(
                tenant_key=None,  # type: ignore[arg-type]
                content="x",
                updated_by="admin@test",
                session=db_session,
            )

    async def test_reset_none_raises(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.reset_orchestrator_prompt(
                tenant_key=None,
                session=db_session,  # type: ignore[arg-type]
            )

    async def test_endpoint_get_returns_400_when_user_has_no_tenant(self):
        from unittest.mock import patch

        from api.endpoints.system_prompts import get_orchestrator_prompt

        tenantless_admin = SimpleNamespace(
            id="ghost",
            username="ghost_admin",
            email="ghost@example.com",
            role="admin",
            tenant_key=None,
        )

        with patch("api.app_state.state") as mock_state:
            mock_state.system_prompt_service = Mock()
            with pytest.raises(HTTPException) as exc_info:
                await get_orchestrator_prompt(current_user=tenantless_admin)
        assert exc_info.value.status_code == 400
        assert "tenant_key" in exc_info.value.detail

    async def test_endpoint_update_returns_400_when_user_has_no_tenant(self):
        from unittest.mock import patch

        from api.endpoints.system_prompts import (
            OrchestratorPromptUpdateRequest,
            update_orchestrator_prompt,
        )

        tenantless_admin = SimpleNamespace(
            id="ghost",
            username="ghost_admin",
            email="ghost@example.com",
            role="admin",
            tenant_key="",
        )
        payload = OrchestratorPromptUpdateRequest(content="some prompt")

        with patch("api.app_state.state") as mock_state:
            mock_state.system_prompt_service = Mock()
            with pytest.raises(HTTPException) as exc_info:
                await update_orchestrator_prompt(payload=payload, current_user=tenantless_admin)
        assert exc_info.value.status_code == 400

    async def test_endpoint_reset_returns_400_when_user_has_no_tenant(self):
        from unittest.mock import patch

        from api.endpoints.system_prompts import reset_orchestrator_prompt

        tenantless_admin = SimpleNamespace(
            id="ghost",
            username="ghost_admin",
            email="ghost@example.com",
            role="admin",
            tenant_key=None,
        )

        with patch("api.app_state.state") as mock_state:
            mock_state.system_prompt_service = Mock()
            with pytest.raises(HTTPException) as exc_info:
                await reset_orchestrator_prompt(current_user=tenantless_admin)
        assert exc_info.value.status_code == 400




def _make_mission_service():
    db_manager = Mock()
    tenant_manager = Mock()
    return MissionOrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
    )


def _make_ctx(override_content: str | None):
    execution = MagicMock()
    execution.agent_id = "agent-001"
    execution.status = "working"

    agent_job = MagicMock()
    agent_job.mission = "Test mission"

    project = MagicMock()
    project.id = "project-001"
    project.name = "Test Project"
    project.description = "Test description"
    project.execution_mode = "multi_terminal"
    project.auto_checkin_enabled = False
    project.auto_checkin_interval = 10

    product = MagicMock()
    product.id = "product-001"
    product.project_path = "/tmp/test"

    return {
        "execution": execution,
        "agent_job": agent_job,
        "project": project,
        "product": product,
        "metadata": {},
        "field_toggles": {},
        "depth_config": {},
        "templates": [],
        "category_metadata": {},
        "integrations": {
            "serena_mcp": {"use_in_prompts": False},
            "git_integration": {"enabled": False},
        },
        "orchestrator_prompt_override": override_content,
    }


class TestPropertyCRuntimeInjection:

    def test_override_present_is_stacked_with_harness(self):
        service = _make_mission_service()
        tenant_a_override = "Custom A prompt -- tenant A specific behavior"
        ctx = _make_ctx(override_content=tenant_a_override)

        response = service._build_orchestrator_response(ctx, job_id="job-A", tenant_key="tk_tenant_A")

        identity = response["orchestrator_identity"]
        assert "Custom A prompt" in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity

    def test_override_present_for_claude_code_includes_harness_reminder(self):
        service = _make_mission_service()
        tenant_override = "# My Custom Orchestrator\nDo X."
        ctx = _make_ctx(override_content=tenant_override)
        ctx["project"].execution_mode = "claude_code_cli"

        response = service._build_orchestrator_response(ctx, job_id="job-cc", tenant_key="tk_tenant_cc")

        identity = response["orchestrator_identity"]
        assert "My Custom Orchestrator" in identity
        assert "CHECK-IN PROTOCOL" in identity
        assert "HARNESS REMINDER OVERRIDE" in identity

    def test_no_override_returns_seed_plus_harness(self):
        service = _make_mission_service()
        ctx = _make_ctx(override_content=None)

        response = service._build_orchestrator_response(ctx, job_id="job-B", tenant_key="tk_tenant_B")

        expected = compose_orchestrator_identity(None, tool="multi_terminal") + "\n\nidentity source: built-in default"
        assert response["orchestrator_identity"] == expected
        assert "MCP Tool Usage" in response["orchestrator_identity"]
        assert "CHECK-IN PROTOCOL" in response["orchestrator_identity"]

    def test_tenant_b_does_not_receive_tenant_a_override(self):
        service = _make_mission_service()
        tenant_a_override = "Custom A prompt -- SECRET A"

        ctx_a = _make_ctx(override_content=tenant_a_override)
        response_a = service._build_orchestrator_response(ctx_a, job_id="job-A", tenant_key="tk_tenant_A")

        ctx_b = _make_ctx(override_content=None)
        response_b = service._build_orchestrator_response(ctx_b, job_id="job-B", tenant_key="tk_tenant_B")

        assert "SECRET A" in response_a["orchestrator_identity"]
        assert "CHECK-IN PROTOCOL" in response_a["orchestrator_identity"]
        assert "SECRET A" not in response_b["orchestrator_identity"]
        assert response_b["orchestrator_identity"] == (
            compose_orchestrator_identity(None, tool="multi_terminal") + "\n\nidentity source: built-in default"
        )




class TestHO1027ThreeLayerIdentity:

    def test_compose_with_none_override_returns_seed_plus_harness(self):
        identity = compose_orchestrator_identity(None, tool="multi_terminal")
        seed = _get_user_facing_orchestrator_seed().strip()
        assert seed in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity
        assert "HARNESS REMINDER OVERRIDE" not in identity

    def test_compose_with_string_override_returns_override_plus_harness(self):
        override = "# My Custom Orchestrator\nDo X."
        identity = compose_orchestrator_identity(override, tool="multi_terminal")
        assert "My Custom Orchestrator" in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity
        assert "Mission Breakdown" not in identity

    def test_compose_tool_gate_claude_code_emits_harness_reminder(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "HARNESS REMINDER OVERRIDE" in identity

    @pytest.mark.parametrize("tool", ["codex", "gemini", "multi_terminal"])
    def test_compose_tool_gate_non_claude_code_omits_harness_reminder(self, tool):
        identity = compose_orchestrator_identity(None, tool=tool)
        assert "HARNESS REMINDER OVERRIDE" not in identity
        assert "CHECK-IN PROTOCOL" in identity

    def test_seed_does_not_contain_harness_mechanics(self):
        seed = _get_user_facing_orchestrator_seed()
        assert "MCP Tool Usage" not in seed
        assert "CHECK-IN PROTOCOL" not in seed
        assert "HARNESS REMINDER OVERRIDE" not in seed
        assert "Orchestrator" in seed

    def test_back_compat_shim_matches_composer(self):
        for tool in ("claude-code", "codex", "gemini", "multi_terminal"):
            assert get_orchestrator_identity_content(tool=tool) == compose_orchestrator_identity(None, tool=tool)

    def test_default_builder_returns_layer_b_only_no_harness_markers(self):
        service = SystemPromptService(db_manager=None)
        default = service._build_default_orchestrator_prompt()
        assert "MCP Tool Usage" not in default
        assert "CHECK-IN PROTOCOL" not in default
        assert "HARNESS REMINDER OVERRIDE" not in default
        assert default
        assert "Orchestrator" in default
        assert default == _get_user_facing_orchestrator_seed().strip()

    def test_compose_with_none_override_and_claude_code_includes_seed_and_harness_reminder(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        seed = _get_user_facing_orchestrator_seed().strip()
        assert seed in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity
        assert "HARNESS REMINDER OVERRIDE" in identity
