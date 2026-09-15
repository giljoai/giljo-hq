# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from giljo_mcp.template_seeder import (
    _get_default_templates_v103,
    _get_mcp_coordination_section,
)
from tests.helpers.product_crew_helper import make_product, seed_crew


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

    async def test_seeds_system_instructions(self, db_session: AsyncSession):
        tenant_key = "test_tenant_system"

        _product, _names = await seed_crew(db_session, tenant_key)
        count = len(_names)

        assert count == 5, "Should seed 5 default templates (orchestrator is system-managed)"

        templates = await _fetch_templates(db_session, tenant_key)

        assert len(templates) == 5, "Should have 5 templates"

        for template in templates:
            assert template.system_instructions is not None, f"{template.role} missing system_instructions"
            assert len(template.system_instructions) > 0, f"{template.role} has empty system_instructions"
            assert "MCP" in template.system_instructions.upper(), f"{template.role} missing MCP content"

    async def test_seeds_user_instructions(self, db_session: AsyncSession):
        tenant_key = "test_tenant_user"

        _product, _names = await seed_crew(db_session, tenant_key)
        count = len(_names)

        assert count == 5

        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            assert template.user_instructions is not None, f"{template.role} missing user_instructions"
            assert len(template.user_instructions) > 0, f"{template.role} has empty user_instructions"

            if template.role == "implementer":
                assert (
                    "implementation" in template.user_instructions.lower()
                    or "implementer" in template.user_instructions.lower()
                )
            elif template.role == "tester":
                assert "test" in template.user_instructions.lower()

    async def test_system_instructions_consistent_for_non_orchestrator(self, db_session: AsyncSession):
        tenant_key = "test_tenant_identical"

        await seed_crew(db_session, tenant_key)

        rows = await _fetch_template_rows(db_session, tenant_key, AgentTemplate.system_instructions)
        system_instructions_list = [row[0] for row in rows]

        assert len(system_instructions_list) == 5, "Should have 5 templates"
        assert len(set(system_instructions_list)) == 1, (
            "All non-orchestrator templates should have identical system_instructions"
        )

    async def test_user_instructions_unique(self, db_session: AsyncSession):
        tenant_key = "test_tenant_unique"

        await seed_crew(db_session, tenant_key)

        rows = await _fetch_template_rows(db_session, tenant_key, AgentTemplate.role, AgentTemplate.user_instructions)
        user_instructions_by_role = {row[0]: row[1] for row in rows}

        assert len(user_instructions_by_role) == 5, "Should have 5 unique roles"

        user_instructions_values = list(user_instructions_by_role.values())
        assert len(set(user_instructions_values)) == 5, "All user_instructions should be unique per role"

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
        tenant_key = "test_tenant_legacy"

        await seed_crew(db_session, tenant_key)

        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            assert template.system_instructions, f"Template {template.role} should have system_instructions"

            actual = template.system_instructions.strip()
            assert len(actual) > 0, f"Template {template.role} system_instructions should not be empty"

            assert "MCP" in actual.upper(), f"{template.role} system_instructions should contain MCP content"

    async def test_required_mcp_content_in_system(self, db_session: AsyncSession):
        tenant_key = "test_tenant_mcp_tools"

        await seed_crew(db_session, tenant_key)

        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            system_inst = template.system_instructions

            from giljo_mcp.branding import MCP_ALIAS, PRODUCT_NAME

            assert f"{PRODUCT_NAME} Agent" in system_inst, f"{template.role} missing {PRODUCT_NAME} Agent header"
            assert "mcp__<server>__<tool>" in system_inst, f"{template.role} should teach the client-prefix note"
            assert f"mcp__{MCP_ALIAS}__get_job_mission" not in system_inst, (
                f"{template.role} tool call must be bare, not prefixed"
            )
            assert "get_job_mission" in system_inst, f"{template.role} should reference get_job_mission in bootstrap"
            assert "full_protocol" in system_inst, f"{template.role} should reference full_protocol in bootstrap"

    async def test_system_instructions_not_in_user(self, db_session: AsyncSession):
        tenant_key = "test_tenant_no_dup"

        await seed_crew(db_session, tenant_key)

        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            user_inst = template.user_instructions.upper()

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
            assert "MCP__GILJO-MCP__ACKNOWLEDGE_JOB" not in user_inst, (
                f"{template.role} user_instructions contains MCP tools (should be in system only)"
            )
            assert "MCP__GILJO-MCP__REPORT_PROGRESS" not in user_inst, (
                f"{template.role} user_instructions contains MCP tools (should be in system only)"
            )

    async def test_idempotent_seeding(self, db_session: AsyncSession):
        tenant_key = "test_tenant_idempotent"

        product, names1 = await seed_crew(db_session, tenant_key)
        assert len(names1) == 5, "First seed should create 5 templates (orchestrator is system-managed)"

        _same, names2 = await seed_crew(db_session, tenant_key, product)
        assert names2 == [], "Second seed of the same product should add nothing"

        templates = await _fetch_templates(db_session, tenant_key)
        assert len(templates) == 5, "Should still have exactly 5 templates after idempotent run"

    async def test_a_second_product_gets_its_own_crew(self, db_session: AsyncSession):
        tenant_key = "test_tenant_second_product"

        _first, names1 = await seed_crew(db_session, tenant_key)
        second = await make_product(db_session, tenant_key, name="Second product")
        _second, names2 = await seed_crew(db_session, tenant_key, second)

        assert len(names2) == 5, "a second product must get its own crew"
        assert set(names1).isdisjoint(names2), "the two crews must not share a name"
        assert all(n.endswith("-2") for n in names2), f"the second crew shares ONE suffix; got {names2}"

        templates = await _fetch_templates(db_session, tenant_key)
        assert len(templates) == 10
        owners = {t.product_id for t in templates}
        assert owners == {_first.id, second.id}, "every agent must be owned by the product it was seeded for"

    async def test_system_instructions_non_null(self, db_session: AsyncSession):
        tenant_key = "test_tenant_non_null"

        await seed_crew(db_session, tenant_key)

        templates = await _fetch_templates(db_session, tenant_key)

        for template in templates:
            assert template.system_instructions is not None, f"{template.role} has NULL system_instructions"
            assert len(template.system_instructions) > 0, f"{template.role} has empty system_instructions"

    async def test_user_instructions_can_be_null(self, db_session: AsyncSession):
        tenant_key = "test_tenant_user_null"

        template = AgentTemplate(
            tenant_key=tenant_key,
            name="test_template",
            category="role",
            role="test_role",
            cli_tool="claude",
            background_color="#FFFFFF",
            description="Test template",
            system_instructions="Test system instructions",
            user_instructions=None,
            model="sonnet",
            version="1.0.0",
            is_active=True,
            is_default=False,
            tags=["test"],
            created_at=datetime.now(UTC),
        )

        db_session.add(template)
        await db_session.commit()

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
        tenant1 = "tenant_a"
        tenant2 = "tenant_b"

        _product1, _names1 = await seed_crew(db_session, tenant1)
        count1 = len(_names1)
        _product2, _names2 = await seed_crew(db_session, tenant2)
        count2 = len(_names2)

        assert count1 == 5, "Tenant A should have 5 templates"
        assert count2 == 5, "Tenant B should have 5 templates"

        templates1 = await _fetch_templates(db_session, tenant1)
        templates2 = await _fetch_templates(db_session, tenant2)

        assert len(templates1) == 5, "Tenant A should have 5 templates"
        assert len(templates2) == 5, "Tenant B should have 5 templates"

        tenant1_ids = {t.id for t in templates1}
        tenant2_ids = {t.id for t in templates2}
        assert tenant1_ids.isdisjoint(tenant2_ids), "Template IDs should be unique across tenants"


class TestMCPCoordinationSection:

    def test_mcp_section_has_tool_call_guidance(self):
        mcp_section = _get_mcp_coordination_section()

        assert "get_job_mission" in mcp_section, "Should have example tool call"
        assert "mcp__giljo_mcp__get_job_mission" not in mcp_section, "Tool call must be bare, not prefixed"
        assert "mcp__<server>__<tool>" in mcp_section, "Should teach the client-prefix note"

    def test_mcp_section_has_proper_structure(self):
        mcp_section = _get_mcp_coordination_section()

        assert "## MCP Tool Usage" in mcp_section, "Should have MCP Tool Usage header"

        assert "native tool calls" in mcp_section.lower(), "Should explain MCP tools are native calls"

        assert "tenant_key" in mcp_section, "Should mention tenant_key auto-injection"

    def test_mcp_section_mentions_full_protocol(self):
        mcp_section = _get_mcp_coordination_section()

        assert "full_protocol" in mcp_section, "Should reference full_protocol for tool signatures"


class TestDefaultTemplatesV103:

    def test_all_six_roles_defined(self):
        templates = _get_default_templates_v103()

        assert len(templates) == 6, "Should have 6 default templates"

        roles = {t["role"] for t in templates}
        expected_roles = {"orchestrator", "analyzer", "implementer", "tester", "reviewer", "documenter"}

        assert roles == expected_roles, f"Missing roles: {expected_roles - roles}"

    def test_all_templates_have_required_fields(self):
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
        templates = _get_default_templates_v103()

        for template in templates:
            assert template["user_instructions"], f"{template['role']} has empty user_instructions"
            assert len(template["user_instructions"]) > 100, f"{template['role']} user_instructions too short"

    def test_behavioral_rules_empty_for_defaults(self):
        templates = _get_default_templates_v103()

        for template in templates:
            assert isinstance(template["behavioral_rules"], list), f"{template['role']} behavioral_rules not a list"
            assert template["behavioral_rules"] == [], f"{template['role']} should have empty behavioral_rules"

    def test_success_criteria_empty_for_defaults(self):
        templates = _get_default_templates_v103()

        for template in templates:
            assert isinstance(template["success_criteria"], list), f"{template['role']} success_criteria not a list"
            assert template["success_criteria"] == [], f"{template['role']} should have empty success_criteria"


class TestBE9259PersonaNeutrality:

    _FORBIDDEN_ROLE2_ROLE3_TERMS = (
        "giljoai mcp",
        "giljo hq",
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
        text = self._render("tester").lower()
        hits = [term for term in self._FORBIDDEN_ROLE2_ROLE3_TERMS if term in text]
        assert not hits, f"Tester persona still contains dogfooding contamination: {hits}"
        assert "is not verification" in text
        assert "scope discipline and escalation" in text

    def test_implementer_persona_is_language_neutral(self):
        text = self._render("implementer").lower()
        hits = [term for term in self._FORBIDDEN_ROLE2_ROLE3_TERMS if term in text]
        assert not hits, f"Implementer persona still contains dogfooding contamination: {hits}"

    def test_documenter_persona_drops_handover_doc_phrasing(self):
        text = self._render("documenter").lower()
        assert "handover doc" not in text

    def test_orchestrator_persona_drops_ticket_ref_and_handover_doc_phrasing(self):
        orchestrator_def = next(t for t in _get_default_templates_v103() if t["role"] == "orchestrator")
        text = orchestrator_def["user_instructions"].lower()
        assert "be-5029" not in text
        assert "handover doc" not in text

    def test_touched_persona_versions_bumped_past_shipped_baseline(self):
        by_role = {t["role"]: t for t in _get_default_templates_v103()}
        assert by_role["orchestrator"]["version"] == "1.1.0"
        assert by_role["implementer"]["version"] == "1.1.0"
        assert by_role["tester"]["version"] == "1.2.0"
        assert by_role["documenter"]["version"] == "1.1.0"
