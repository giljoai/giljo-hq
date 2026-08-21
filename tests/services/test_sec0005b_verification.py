# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
SEC-0005b verification tests (tester agent).

Complements the implementer's tests in test_sec0005b_system_prompt_tenant_scope.py
with the three properties from the verification work order:

- Property A: Tenant isolation of orchestrator prompt override.
  Tenant A's override is invisible to tenant B, and tenant A's reset does not
  disturb tenant B's state.

- Property B: tenant_key is required.
  Service raises ValueError for empty/None tenant_key on get/update/reset.
  The HTTP endpoint returns 400 when current_user.tenant_key is None.

- Property C: Runtime injection correctness.
  _build_orchestrator_response injects the tenant's override into
  response["orchestrator_identity"] when present, and falls back to the default
  content for other tenants.
"""

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


# ---------------------------------------------------------------------------
# Property A: Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPropertyATenantIsolation:
    """Tenant A's override must not affect tenant B."""

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
        # Tenant B must NEVER see tenant A's content.
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
        # Tenant B has no override at all; its state is the default.
        await db_session.commit()

        # Snapshot B's default BEFORE reset.
        b_before = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)

        # Reset A.
        await service.reset_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        await db_session.commit()

        # A returns to default.
        a_after = await service.get_orchestrator_prompt(tenant_key=tenant_a, session=db_session)
        # B is untouched -- still default, byte-identical to the pre-reset snapshot.
        b_after = await service.get_orchestrator_prompt(tenant_key=tenant_b, session=db_session)

        assert a_after.is_override is False
        assert b_after.is_override is False
        assert b_before.content == b_after.content


# ---------------------------------------------------------------------------
# Property B: tenant_key required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPropertyBTenantRequired:
    """get/update/reset raise ValueError when tenant_key missing, endpoint returns 400."""

    async def test_get_empty_string_raises(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            await service.get_orchestrator_prompt(tenant_key="", session=db_session)

    async def test_get_none_raises(self, db_manager, db_session):
        service = SystemPromptService(db_manager=db_manager)
        with pytest.raises(ValueError, match="tenant_key"):
            # Type-ignore: intentionally passing None to verify runtime guard.
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
        """GET /orchestrator-prompt returns HTTP 400 when current_user.tenant_key is None."""
        from unittest.mock import patch

        from api.endpoints.system_prompts import get_orchestrator_prompt

        tenantless_admin = SimpleNamespace(
            id="ghost",
            username="ghost_admin",
            email="ghost@example.com",
            role="admin",
            tenant_key=None,
        )

        # Service must be available so the 400 tenant-guard is the one that fires.
        with patch("api.app_state.state") as mock_state:
            mock_state.system_prompt_service = Mock()
            with pytest.raises(HTTPException) as exc_info:
                await get_orchestrator_prompt(current_user=tenantless_admin)
        assert exc_info.value.status_code == 400
        assert "tenant_key" in exc_info.value.detail

    async def test_endpoint_update_returns_400_when_user_has_no_tenant(self):
        """PUT /orchestrator-prompt returns HTTP 400 when current_user.tenant_key is None."""
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
            tenant_key="",  # whitespace/empty variant
        )
        payload = OrchestratorPromptUpdateRequest(content="some prompt")

        with patch("api.app_state.state") as mock_state:
            mock_state.system_prompt_service = Mock()
            with pytest.raises(HTTPException) as exc_info:
                await update_orchestrator_prompt(payload=payload, current_user=tenantless_admin)
        assert exc_info.value.status_code == 400

    async def test_endpoint_reset_returns_400_when_user_has_no_tenant(self):
        """POST /orchestrator-prompt/reset returns HTTP 400 when tenant_key is None."""
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


# ---------------------------------------------------------------------------
# Property C: Runtime injection correctness in _build_orchestrator_response
# ---------------------------------------------------------------------------


def _make_mission_service():
    """Build a MissionOrchestrationService with mocked deps (no DB needed)."""
    db_manager = Mock()
    tenant_manager = Mock()
    return MissionOrchestrationService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
    )


def _make_ctx(override_content: str | None):
    """
    Build the minimum ctx dict that _build_orchestrator_response consumes.

    Keys observed from the service implementation:
      execution, agent_job, project, product, metadata, field_toggles,
      depth_config, templates, category_metadata, integrations,
      orchestrator_prompt_override.
    """
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
    """_build_orchestrator_response must wire the tenant's override into the response.

    HO1027 (three-layer identity refactor): When an override is set, the
    response is the override content STACKED with the system harness
    (MCP Tool Usage + CHECK-IN PROTOCOL [+ HARNESS REMINDER OVERRIDE for
    Claude Code]). The harness is ALWAYS appended — even when the admin has
    saved a custom seed — so harness mechanics never leak into the textarea
    but always reach the spawned orchestrator.
    """

    def test_override_present_is_stacked_with_harness(self):
        """When ctx carries a tenant override, response['orchestrator_identity'] is override + harness."""
        service = _make_mission_service()
        tenant_a_override = "Custom A prompt -- tenant A specific behavior"
        ctx = _make_ctx(override_content=tenant_a_override)

        response = service._build_orchestrator_response(ctx, job_id="job-A", tenant_key="tk_tenant_A")

        identity = response["orchestrator_identity"]
        # Override content present
        assert "Custom A prompt" in identity
        # Harness markers ALWAYS appended (multi_terminal in this ctx → no HARNESS REMINDER)
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity

    def test_override_present_for_claude_code_includes_harness_reminder(self):
        """Claude Code orchestrators with admin override still see HARNESS REMINDER OVERRIDE."""
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
        """When ctx has no override, response['orchestrator_identity'] is seed + harness."""
        service = _make_mission_service()
        ctx = _make_ctx(override_content=None)

        response = service._build_orchestrator_response(ctx, job_id="job-B", tenant_key="tk_tenant_B")

        # Multi_terminal default tool — no HARNESS REMINDER, but harness markers present.
        # FE-9408: the composed bytes are unchanged; the provenance line is appended to
        # them. Stating the delta literally is what makes this a content pin rather than
        # a test that would accept any edit to the composition.
        expected = compose_orchestrator_identity(None, tool="multi_terminal") + "\n\nidentity source: built-in default"
        assert response["orchestrator_identity"] == expected
        assert "MCP Tool Usage" in response["orchestrator_identity"]
        assert "CHECK-IN PROTOCOL" in response["orchestrator_identity"]

    def test_tenant_b_does_not_receive_tenant_a_override(self):
        """
        Simulates the critical cross-tenant case: tenant A has a custom prompt,
        tenant B is built in the same process. Because the ctx is the per-call
        tenant-scoped lookup, tenant B's response MUST NOT contain A's string.
        """
        service = _make_mission_service()
        tenant_a_override = "Custom A prompt -- SECRET A"

        # Tenant A call -- ctx carries A's override.
        ctx_a = _make_ctx(override_content=tenant_a_override)
        response_a = service._build_orchestrator_response(ctx_a, job_id="job-A", tenant_key="tk_tenant_A")

        # Tenant B call -- ctx has no override (A's override is invisible to B).
        ctx_b = _make_ctx(override_content=None)
        response_b = service._build_orchestrator_response(ctx_b, job_id="job-B", tenant_key="tk_tenant_B")

        # Tenant A: override stacked with harness.
        assert "SECRET A" in response_a["orchestrator_identity"]
        assert "CHECK-IN PROTOCOL" in response_a["orchestrator_identity"]
        # Critical invariant: tenant B's response must not leak tenant A's custom content.
        assert "SECRET A" not in response_b["orchestrator_identity"]
        # Tenant B: seed stacked with harness (default multi_terminal tool), plus the
        # FE-9408 provenance line -- which must say "built-in default" here, because
        # tenant B has no override and must not be told it is wearing one.
        assert response_b["orchestrator_identity"] == (
            compose_orchestrator_identity(None, tool="multi_terminal") + "\n\nidentity source: built-in default"
        )


# ---------------------------------------------------------------------------
# HO1027: Three-Layer Identity Refactor regression tests
# ---------------------------------------------------------------------------


class TestHO1027ThreeLayerIdentity:
    """Direct unit coverage for compose_orchestrator_identity()."""

    def test_compose_with_none_override_returns_seed_plus_harness(self):
        identity = compose_orchestrator_identity(None, tool="multi_terminal")
        seed = _get_user_facing_orchestrator_seed().strip()
        assert seed in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity
        # Multi-terminal tool: no Claude-Code-only HARNESS REMINDER OVERRIDE.
        assert "HARNESS REMINDER OVERRIDE" not in identity

    def test_compose_with_string_override_returns_override_plus_harness(self):
        override = "# My Custom Orchestrator\nDo X."
        identity = compose_orchestrator_identity(override, tool="multi_terminal")
        # Override body present, harness markers appended, default seed NOT injected.
        assert "My Custom Orchestrator" in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity
        # The seed-only "Mission Breakdown" core-responsibility line should NOT
        # leak in when an override replaces the seed.
        assert "Mission Breakdown" not in identity

    def test_compose_tool_gate_claude_code_emits_harness_reminder(self):
        identity = compose_orchestrator_identity(None, tool="claude-code")
        assert "HARNESS REMINDER OVERRIDE" in identity

    @pytest.mark.parametrize("tool", ["codex", "gemini", "multi_terminal"])
    def test_compose_tool_gate_non_claude_code_omits_harness_reminder(self, tool):
        identity = compose_orchestrator_identity(None, tool=tool)
        assert "HARNESS REMINDER OVERRIDE" not in identity
        # But CHECK-IN PROTOCOL is still present for every tool.
        assert "CHECK-IN PROTOCOL" in identity

    def test_seed_does_not_contain_harness_mechanics(self):
        """Layer B (admin textarea content) must not include harness wiring."""
        seed = _get_user_facing_orchestrator_seed()
        assert "MCP Tool Usage" not in seed
        assert "CHECK-IN PROTOCOL" not in seed
        assert "HARNESS REMINDER OVERRIDE" not in seed
        # But identity preamble + behavioral pieces present.
        assert "Orchestrator" in seed

    def test_back_compat_shim_matches_composer(self):
        """get_orchestrator_identity_content(tool) == compose_orchestrator_identity(None, tool)."""
        for tool in ("claude-code", "codex", "gemini", "multi_terminal"):
            assert get_orchestrator_identity_content(tool=tool) == compose_orchestrator_identity(None, tool=tool)

    def test_default_builder_returns_layer_b_only_no_harness_markers(self):
        """AC3: SystemPromptService._build_default_orchestrator_prompt() must
        return ONLY the user-facing seed (Layer B) — no harness mechanics.

        The admin textarea shows the result of this method. If harness markers
        leak in, admins could accidentally delete them when editing, and the
        composer would double-stack on save.
        """
        service = SystemPromptService(db_manager=None)
        default = service._build_default_orchestrator_prompt()
        # Harness markers must NOT appear in the admin-textarea content.
        assert "MCP Tool Usage" not in default
        assert "CHECK-IN PROTOCOL" not in default
        assert "HARNESS REMINDER OVERRIDE" not in default
        # But the seed body must be present and non-empty.
        assert default
        assert "Orchestrator" in default
        # Cross-check: equals the canonical seed (stripped).
        assert default == _get_user_facing_orchestrator_seed().strip()

    def test_compose_with_none_override_and_claude_code_includes_seed_and_harness_reminder(self):
        """AC1 explicit: None override + claude-code → seed + harness + HARNESS REMINDER."""
        identity = compose_orchestrator_identity(None, tool="claude-code")
        seed = _get_user_facing_orchestrator_seed().strip()
        assert seed in identity
        assert "MCP Tool Usage" in identity
        assert "CHECK-IN PROTOCOL" in identity
        assert "HARNESS REMINDER OVERRIDE" in identity
