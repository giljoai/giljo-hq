# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Comprehensive tests for template_seeder.py dual-field system.

Tests the seeding of system_instructions (protected MCP coordination) and
user_instructions (editable role-specific guidance) in agent templates.

Handover 0106: Dual-Field System
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_coordination_section,
    seed_tenant_templates,
)


async def _fetch_templates(db_session: AsyncSession, tenant_key: str):
    with tenant_session_context(db_session, tenant_key):
        result = await db_session.execute(select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
        return result.scalars().all()


async def _fetch_template_rows(db_session: AsyncSession, tenant_key: str, *columns):
    with tenant_session_context(db_session, tenant_key):
        result = await db_session.execute(select(*columns).where(AgentTemplate.tenant_key == tenant_key))
        return result.fetchall()


@pytest.mark.asyncio
class TestTemplateSeederDualField:
    """Test suite for dual-field template seeding (Handover 0106)."""

    async def test_seeds_system_instructions(self, db_session: AsyncSession):
        """Verify system_instructions populated for all templates."""
        tenant_key = "test_tenant_system"

        # Seed templates
        count = await seed_tenant_templates(db_session, tenant_key)

        # Verify count
        assert count == 5, "Should seed 5 default templates (orchestrator is system-managed)"

        # Fetch all templates
        templates = await _fetch_templates(db_session, tenant_key)

        # Verify all have system_instructions
        assert len(templates) == 5, "Should have 5 templates"

        for template in templates:
            assert template.system_instructions is not None, f"{template.role} missing system_instructions"
            assert len(template.system_instructions) > 0, f"{template.role} has empty system_instructions"
            assert "MCP" in template.system_instructions.upper(), f"{template.role} missing MCP content"

    async def test_seeds_user_instructions(self, db_session: AsyncSession):
        """Verify user_instructions populated with role-specific content."""
        tenant_key = "test_tenant_user"

        # Seed templates
        count = await seed_tenant_templates(db_session, tenant_key)

        # Verify count
        assert count == 5

        # Fetch all templates
        templates = await _fetch_templates(db_session, tenant_key)

        # Verify all have user_instructions
        for template in templates:
            assert template.user_instructions is not None, f"{template.role} missing user_instructions"
            assert len(template.user_instructions) > 0, f"{template.role} has empty user_instructions"

            # Verify role-specific content (each role should have unique instructions)
            if template.role == "implementer":
                assert (
                    "implementation" in template.user_instructions.lower()
                    or "implementer" in template.user_instructions.lower()
                )
            elif template.role == "tester":
                assert "test" in template.user_instructions.lower()

    async def test_system_instructions_consistent_for_non_orchestrator(self, db_session: AsyncSession):
        """Verify all non-orchestrator templates get same system_instructions."""
        tenant_key = "test_tenant_identical"

        # Seed templates
        await seed_tenant_templates(db_session, tenant_key)

        # Fetch all templates (all are non-orchestrator since orchestrator is system-managed)
        rows = await _fetch_template_rows(db_session, tenant_key, AgentTemplate.system_instructions)
        system_instructions_list = [row[0] for row in rows]

        # Verify all non-orchestrator system instructions are identical
        assert len(system_instructions_list) == 5, "Should have 5 templates"
        assert len(set(system_instructions_list)) == 1, (
            "All non-orchestrator templates should have identical system_instructions"
        )

    async def test_user_instructions_unique(self, db_session: AsyncSession):
        """Verify each role gets unique user_instructions."""
        tenant_key = "test_tenant_unique"

        # Seed templates
        await seed_tenant_templates(db_session, tenant_key)

        # Fetch all templates
        rows = await _fetch_template_rows(db_session, tenant_key, AgentTemplate.role, AgentTemplate.user_instructions)
        user_instructions_by_role = {row[0]: row[1] for row in rows}

        # Verify each role has unique user instructions (orchestrator is system-managed, not seeded)
        assert len(user_instructions_by_role) == 5, "Should have 5 unique roles"

        # Verify no duplicates (all user_instructions are unique)
        user_instructions_values = list(user_instructions_by_role.values())
        assert len(set(user_instructions_values)) == 5, "All user_instructions should be unique per role"

        # Verify each role has content matching its role
        assert (
            "analyzer" in user_instructions_by_role["analyzer"].lower()
            or "analysis" in user_instructions_by_role["analyzer"].lower()
        )
        assert (
            "implementer" in user_instructions_by_role["implementer"].lower()
            or "implementation" in user_instructions_by_role["implementer"].lower()
        )
        assert (
            "tester" in user_instructions_by_role["tester"].lower()
            or "test" in user_instructions_by_role["tester"].lower()
        )
        assert (
            "reviewer" in user_instructions_by_role["reviewer"].lower()
            or "review" in user_instructions_by_role["reviewer"].lower()
        )
        assert (
            "documenter" in user_instructions_by_role["documenter"].lower()
            or "documentation" in user_instructions_by_role["documenter"].lower()
        )

    async def test_system_instructions_populated(self, db_session: AsyncSession):
        """Verify system_instructions populated correctly."""
        tenant_key = "test_tenant_legacy"

        # Seed templates
        await seed_tenant_templates(db_session, tenant_key)

        # Fetch all templates
        templates = await _fetch_templates(db_session, tenant_key)

        # Verify system_instructions field populated
        for template in templates:
            # system_instructions should be populated
            assert template.system_instructions, f"Template {template.role} should have system_instructions"

            # Check content is reasonable
            actual = template.system_instructions.strip()
            assert len(actual) > 0, f"Template {template.role} system_instructions should not be empty"

            # Verify MCP content is present in system_instructions
            assert "MCP" in actual.upper(), f"{template.role} system_instructions should contain MCP content"

    async def test_required_mcp_content_in_system(self, db_session: AsyncSession):
        """Verify key MCP bootstrap content present in system_instructions.

        Handover 0813: system_instructions is now a slim bootstrap (~10 lines)
        that directs agents to fetch full protocols via get_job_mission().
        """
        tenant_key = "test_tenant_mcp_tools"

        # Seed templates
        await seed_tenant_templates(db_session, tenant_key)

        # Fetch all templates
        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            system_inst = template.system_instructions

            # BE-9275b: Bootstrap should reference the current product name's Agent header.
            from giljo_mcp.branding import MCP_ALIAS, PRODUCT_NAME

            assert f"{PRODUCT_NAME} Agent" in system_inst, f"{template.role} missing {PRODUCT_NAME} Agent header"
            # BE-9012d (F1): tool names are bare now (this shared bootstrap renders to
            # Codex/Gemini/Desktop too, where the Claude Code prefix is wrong) -- it
            # instead teaches that a client MAY expose tools prefixed.
            assert "mcp__<server>__<tool>" in system_inst, f"{template.role} should teach the client-prefix note"
            assert f"mcp__{MCP_ALIAS}__get_job_mission" not in system_inst, (
                f"{template.role} tool call must be bare, not prefixed"
            )
            # Should reference get_job_mission for full protocol delivery
            assert "get_job_mission" in system_inst, f"{template.role} should reference get_job_mission in bootstrap"
            # Should reference full_protocol
            assert "full_protocol" in system_inst, f"{template.role} should reference full_protocol in bootstrap"

    async def test_system_instructions_not_in_user(self, db_session: AsyncSession):
        """Verify system_instructions content NOT duplicated in user_instructions."""
        tenant_key = "test_tenant_no_dup"

        # Seed templates
        await seed_tenant_templates(db_session, tenant_key)

        # Fetch all templates
        templates = await _fetch_templates(db_session, tenant_key)

        # Verify user_instructions don't contain MCP coordination content
        for template in templates:
            user_inst = template.user_instructions.upper()

            # BE-9361: both brand generations -- the bootstrap says "Giljo HQ"
            # now, so pinning only the pre-rename wording made this vacuous.
            for bootstrap_phrase in (
                "YOU ARE PART OF A GILJOAI MCP ORCHESTRATION SYSTEM",
                "YOU ARE PART OF A GILJO HQ ORCHESTRATION SYSTEM",
            ):
                assert bootstrap_phrase not in user_inst, (
                    f"{template.role} user_instructions contains MCP bootstrap prose (should be in system only)"
                )
            assert "STARTUP (MANDATORY)" not in user_inst, (
                f"{template.role} user_instructions contains MCP startup prose (should be in system only)"
            )
            # User instructions should NOT contain MCP tools (those are in system)
            assert "MCP__GILJO-MCP__ACKNOWLEDGE_JOB" not in user_inst, (
                f"{template.role} user_instructions contains MCP tools (should be in system only)"
            )
            assert "MCP__GILJO-MCP__REPORT_PROGRESS" not in user_inst, (
                f"{template.role} user_instructions contains MCP tools (should be in system only)"
            )

    async def test_idempotent_seeding(self, db_session: AsyncSession):
        """Verify seeding is idempotent (safe to run multiple times)."""
        tenant_key = "test_tenant_idempotent"

        # Seed first time
        count1 = await seed_tenant_templates(db_session, tenant_key)
        assert count1 == 5, "First seed should create 5 templates (orchestrator is system-managed)"

        # Seed second time (should skip)
        count2 = await seed_tenant_templates(db_session, tenant_key)
        assert count2 == 0, "Second seed should skip (idempotent)"

        # Verify still only 5 templates
        templates = await _fetch_templates(db_session, tenant_key)
        assert len(templates) == 5, "Should still have exactly 5 templates after idempotent run"

    async def test_system_instructions_non_null(self, db_session: AsyncSession):
        """Verify system_instructions is never NULL."""
        tenant_key = "test_tenant_non_null"

        # Seed templates
        await seed_tenant_templates(db_session, tenant_key)

        # Fetch all templates and verify system_instructions NOT NULL
        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            assert template.system_instructions is not None, f"{template.role} has NULL system_instructions"
            assert len(template.system_instructions) > 0, f"{template.role} has empty system_instructions"

    async def test_user_instructions_can_be_null(self, db_session: AsyncSession):
        """Verify user_instructions can be NULL (optional field)."""
        # This test verifies schema allows NULL user_instructions
        # (though current implementation always populates it)
        tenant_key = "test_tenant_user_null"

        # Create template with NULL user_instructions
        template = AgentTemplate(
            tenant_key=tenant_key,
            name="test_template",
            category="role",
            role="test_role",
            cli_tool="claude",
            background_color="#FFFFFF",
            description="Test template",
            system_instructions="Test system instructions",
            user_instructions=None,  # NULL allowed
            model="sonnet",
            version="1.0.0",
            is_active=True,
            is_default=False,
            tags=["test"],
            created_at=datetime.now(UTC),
        )

        db_session.add(template)
        await db_session.commit()

        # Fetch and verify
        with tenant_session_context(db_session, tenant_key):
            result = await db_session.execute(
                select(AgentTemplate).where(
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.name == "test_template",
                )
            )
            fetched = result.scalar_one()

        assert fetched.system_instructions is not None, "system_instructions should not be NULL"
        assert fetched.user_instructions is None, "user_instructions should be NULL as set"

    async def test_multi_tenant_isolation(self, db_session: AsyncSession):
        """Verify templates are isolated by tenant_key."""
        tenant1 = "tenant_a"
        tenant2 = "tenant_b"

        # Seed both tenants
        count1 = await seed_tenant_templates(db_session, tenant1)
        count2 = await seed_tenant_templates(db_session, tenant2)

        assert count1 == 5, "Tenant A should have 5 templates"
        assert count2 == 5, "Tenant B should have 5 templates"

        # Verify isolation
        templates1 = await _fetch_templates(db_session, tenant1)
        templates2 = await _fetch_templates(db_session, tenant2)

        assert len(templates1) == 5, "Tenant A should have 5 templates"
        assert len(templates2) == 5, "Tenant B should have 5 templates"

        # Verify no cross-tenant contamination
        tenant1_ids = {t.id for t in templates1}
        tenant2_ids = {t.id for t in templates2}
        assert tenant1_ids.isdisjoint(tenant2_ids), "Template IDs should be unique across tenants"


class TestMCPCoordinationSection:
    """Test MCP coordination section generation."""

    def test_mcp_section_has_tool_call_guidance(self):
        """Verify MCP section has tool call format guidance."""
        mcp_section = _get_mcp_coordination_section()

        # After Handover 0431 slimming, the MCP section only contains the
        # "MCP tools are native calls" warning and an example tool call.
        # BE-9012d (F1): tool names are bare now (this shared section renders to
        # Codex/Gemini/Desktop too, where the Claude Code prefix is wrong).
        assert "get_job_mission" in mcp_section, "Should have example tool call"
        assert "mcp__giljo_mcp__get_job_mission" not in mcp_section, "Tool call must be bare, not prefixed"
        assert "mcp__<server>__<tool>" in mcp_section, "Should teach the client-prefix note"

    def test_mcp_section_has_proper_structure(self):
        """Verify MCP section has proper markdown structure."""
        mcp_section = _get_mcp_coordination_section()

        # Should have proper markdown header (slimmed in 0431)
        assert "## MCP Tool Usage" in mcp_section, "Should have MCP Tool Usage header"

        # Should mention native tool calls
        assert "native tool calls" in mcp_section.lower(), "Should explain MCP tools are native calls"

        # Should mention tenant_key auto-injection
        assert "tenant_key" in mcp_section, "Should mention tenant_key auto-injection"

    def test_mcp_section_mentions_full_protocol(self):
        """Verify MCP section references full_protocol for detailed tool signatures."""
        mcp_section = _get_mcp_coordination_section()

        # Should reference full_protocol for detailed information
        assert "full_protocol" in mcp_section, "Should reference full_protocol for tool signatures"


class TestDefaultTemplatesV103:
    """Test default template definitions."""

    def test_all_six_roles_defined(self):
        """Verify all 6 roles have template definitions."""
        templates = _get_default_templates_v103()

        assert len(templates) == 6, "Should have 6 default templates"

        roles = {t["role"] for t in templates}
        expected_roles = {"orchestrator", "analyzer", "implementer", "tester", "reviewer", "documenter"}

        assert roles == expected_roles, f"Missing roles: {expected_roles - roles}"

    def test_all_templates_have_required_fields(self):
        """Verify all templates have required fields."""
        templates = _get_default_templates_v103()

        required_fields = {
            "name",
            "role",
            "cli_tool",
            "background_color",
            "description",
            "user_instructions",
            "model",
            "behavioral_rules",
            "success_criteria",
            "is_active",
            "is_default",
            "version",
        }

        for template in templates:
            template_fields = set(template.keys())
            missing_fields = required_fields - template_fields

            assert not missing_fields, f"{template['role']} missing fields: {missing_fields}"

    def test_user_instructions_not_empty(self):
        """Verify user_instructions is not empty for all roles."""
        templates = _get_default_templates_v103()

        for template in templates:
            assert template["user_instructions"], f"{template['role']} has empty user_instructions"
            assert len(template["user_instructions"]) > 100, f"{template['role']} user_instructions too short"

    def test_behavioral_rules_empty_for_defaults(self):
        """Verify behavioral_rules is empty list for all default roles (content in user_instructions prose)."""
        templates = _get_default_templates_v103()

        for template in templates:
            assert isinstance(template["behavioral_rules"], list), f"{template['role']} behavioral_rules not a list"
            assert template["behavioral_rules"] == [], f"{template['role']} should have empty behavioral_rules"

    def test_success_criteria_empty_for_defaults(self):
        """Verify success_criteria is empty list for all default roles (content in user_instructions prose)."""
        templates = _get_default_templates_v103()

        for template in templates:
            assert isinstance(template["success_criteria"], list), f"{template['role']} success_criteria not a list"
            assert template["success_criteria"] == [], f"{template['role']} should have empty success_criteria"


class TestBE9259PersonaNeutrality:
    """BE-9259: the tester/implementer/documenter seed personas must not teach a
    customer's agents that the software under test IS Giljo HQ, nor hand them
    THIS repo's own toolchain/edition/tenancy rules as if they were the customer's.

    A customer product with a non-Python stack and no CE/SaaS editions must
    receive a tester persona that names their own product (or no product at
    all) and carries none of our stack/edition/tenant mandates. Role-1 system
    branding (Giljo HQ as the orchestration platform) is untouched and
    deliberately not asserted against here.
    """

    # Terms that would re-introduce dogfooding contamination if they appeared
    # in the customer-facing tester/implementer/documenter prose. Checked
    # case-insensitively as substrings of the rendered text.
    _FORBIDDEN_ROLE2_ROLE3_TERMS = (
        # BE-9361: both brand generations -- the product renamed to "Giljo HQ",
        # which does not contain the legacy literal, so keeping only the old one
        # would let post-rename Role-2 contamination through.
        "giljoai mcp",  # the platform asserted as the software UNDER TEST (Role 2)
        "giljo hq",  # same, under the current brand
        "pytest",
        "vitest",
        "playwright",
        "@vue/test-utils",
        "@pinia/testing",
        "jsdom",
        "tenant_key",
        "tenant isolation",
        "saas test",
        "ce test",
        "tests/saas",
        "real postgresql",
        "ruff",
        "black",
        "use pathlib",
        "handover doc",
    )

    def _render(self, role: str) -> str:
        template = next(t for t in _get_default_templates_v103() if t["role"] == role)
        return f"{template['description']}\n{template['user_instructions']}"

    def test_tester_persona_is_customer_neutral(self):
        """The tester seed must name no toolchain/edition/tenancy specifics of
        THIS repo — a Go/Rust/whatever customer product gets clean guidance."""
        text = self._render("tester").lower()
        hits = [term for term in self._FORBIDDEN_ROLE2_ROLE3_TERMS if term in text]
        assert not hits, f"Tester persona still contains dogfooding contamination: {hits}"
        # The generic verification discipline must survive the rewrite.
        assert "is not verification" in text
        assert "scope discipline and escalation" in text

    def test_implementer_persona_is_language_neutral(self):
        """The implementer seed must not mandate our Python-specific tooling."""
        text = self._render("implementer").lower()
        hits = [term for term in self._FORBIDDEN_ROLE2_ROLE3_TERMS if term in text]
        assert not hits, f"Implementer persona still contains dogfooding contamination: {hits}"

    def test_documenter_persona_drops_handover_doc_phrasing(self):
        """'Handover documents' is our internal process artifact, not a customer
        deliverable — the documenter seed must speak of plain project docs."""
        text = self._render("documenter").lower()
        assert "handover doc" not in text

    def test_orchestrator_persona_drops_ticket_ref_and_handover_doc_phrasing(self):
        """The orchestrator seed must not cite our internal ticket refs or call
        its own success criterion a 'handover document'."""
        orchestrator_def = next(t for t in _get_default_templates_v103() if t["role"] == "orchestrator")
        text = orchestrator_def["user_instructions"].lower()
        assert "be-5029" not in text
        assert "handover doc" not in text

    def test_touched_persona_versions_bumped_past_shipped_baseline(self):
        """BE-9259 rewrote prose for orchestrator/implementer/tester/documenter —
        per the seeder's own per-role version convention (see tester's prior
        1.0.0 -> 1.1.0 bump), a content rewrite bumps that def's version string
        so the change is visible on the template row / its archive history."""
        by_role = {t["role"]: t for t in _get_default_templates_v103()}
        assert by_role["orchestrator"]["version"] == "1.1.0"
        assert by_role["implementer"]["version"] == "1.1.0"
        assert by_role["tester"]["version"] == "1.2.0"
        assert by_role["documenter"]["version"] == "1.1.0"
