# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid

import pytest

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import AgentExecution, AgentJob, AgentTemplate, Product, Project
from tests.helpers.test_db_helper import purge_tenant_rows


@pytest.mark.asyncio
class TestCLIModeRules:

    @pytest.fixture
    async def cli_mode_context(self, db_manager: DatabaseManager):
        tenant_key = f"test_tenant_{uuid.uuid4().hex[:8]}"

        async with db_manager.get_session_async() as session:
            product = Product(
                tenant_key=tenant_key,
                name="Test Product for CLI Rules",
                description="Product for testing CLI mode rules",
                is_active=True,
            )
            session.add(product)
            await session.flush()

            project = Project(
                tenant_key=tenant_key,
                product_id=product.id,
                name="Test Project for CLI Rules",
                description="Project for testing CLI mode rules",
                mission="Test mission for CLI mode validation",
                status="active",
                execution_mode="claude_code_cli",
                series_number=random.randint(1, 9000),
            )
            session.add(project)
            await session.flush()

            orchestrator_id = str(uuid.uuid4())

            job = AgentJob(
                job_id=orchestrator_id,
                tenant_key=tenant_key,
                project_id=str(project.id),
                mission="CLI mode orchestrator mission for testing",
                job_type="orchestrator",
                status="active",
                job_metadata={
                    "execution_mode": "claude_code_cli",
                    "field_toggles": {},
                    "depth_config": {},
                },
            )
            session.add(job)
            await session.flush()

            orchestrator = AgentExecution(
                job_id=orchestrator_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                agent_name="CLI Mode Orchestrator",
                status="waiting",
            )
            session.add(orchestrator)

            template = AgentTemplate(
                tenant_key=tenant_key,
                name="implementer",
                role="implementer",
                description="Implementation specialist",
                system_instructions="# Implementer\nAn implementation specialist agent.",
                is_active=True,
            )
            session.add(template)

            await session.commit()

            yield {
                "tenant_key": tenant_key,
                "orchestrator_id": orchestrator_id,
                "project_id": str(project.id),
                "product_id": str(product.id),
            }

        await purge_tenant_rows(db_manager, tenant_key)

    @pytest.fixture
    async def multi_terminal_context(self, db_manager: DatabaseManager):
        tenant_key = f"test_tenant_{uuid.uuid4().hex[:8]}"

        async with db_manager.get_session_async() as session:
            product = Product(
                tenant_key=tenant_key,
                name="Test Product for Multi-Terminal",
                description="Product for testing multi-terminal mode",
                is_active=True,
            )
            session.add(product)
            await session.flush()

            project = Project(
                tenant_key=tenant_key,
                product_id=product.id,
                name="Test Project for Multi-Terminal",
                description="Project for testing multi-terminal mode",
                mission="Test mission for multi-terminal mode",
                status="active",
                series_number=random.randint(1, 9000),
            )
            session.add(project)
            await session.flush()

            orchestrator_id = str(uuid.uuid4())

            job = AgentJob(
                job_id=orchestrator_id,
                tenant_key=tenant_key,
                project_id=str(project.id),
                mission="Multi-terminal orchestrator mission for testing",
                job_type="orchestrator",
                status="active",
                job_metadata={
                    "execution_mode": "multi_terminal",
                    "field_toggles": {},
                    "depth_config": {},
                },
            )
            session.add(job)
            await session.flush()

            orchestrator = AgentExecution(
                job_id=orchestrator_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                agent_name="Multi-Terminal Orchestrator",
                status="waiting",
            )
            session.add(orchestrator)

            await session.commit()

            yield {
                "tenant_key": tenant_key,
                "orchestrator_id": orchestrator_id,
                "project_id": str(project.id),
                "product_id": str(product.id),
            }

        await purge_tenant_rows(db_manager, tenant_key)

    async def test_cli_mode_response_includes_cli_mode_rules(
        self,
        db_manager: DatabaseManager,
        cli_mode_context: dict,
    ):
        from giljo_mcp.tenant import TenantManager
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        tenant_manager = TenantManager()
        tool_accessor = ToolAccessor(db_manager, tenant_manager)

        result = await tool_accessor._mission_service.get_staging_instructions(
            job_id=cli_mode_context["orchestrator_id"],
            tenant_key=cli_mode_context["tenant_key"],
        )

        assert "error" not in result, f"Unexpected error: {result.get('message')}"

        assert "cli_mode_rules" in result, "CLI mode response should include cli_mode_rules"

        cli_rules = result["cli_mode_rules"]
        assert isinstance(cli_rules, dict), "cli_mode_rules should be a dict"

    async def test_cli_mode_rules_contains_required_fields(
        self,
        db_manager: DatabaseManager,
        cli_mode_context: dict,
    ):
        from giljo_mcp.tenant import TenantManager
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        tenant_manager = TenantManager()
        tool_accessor = ToolAccessor(db_manager, tenant_manager)

        result = await tool_accessor._mission_service.get_staging_instructions(
            job_id=cli_mode_context["orchestrator_id"],
            tenant_key=cli_mode_context["tenant_key"],
        )

        assert "cli_mode_rules" in result
        cli_rules = result["cli_mode_rules"]

        required_fields = [
            "agent_display_name_usage",
            "agent_name_usage",
            "task_tool_mapping",
            "validation",
        ]

        for field in required_fields:
            assert field in cli_rules, f"cli_mode_rules missing required field: {field}"

        assert cli_rules["validation"] == "soft", "validation should be 'soft'"

        assert "template_locations" not in cli_rules, "retired template_locations is back in cli_mode_rules"

    async def test_cli_mode_response_includes_spawning_examples(
        self,
        db_manager: DatabaseManager,
        cli_mode_context: dict,
    ):
        from giljo_mcp.tenant import TenantManager
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        tenant_manager = TenantManager()
        tool_accessor = ToolAccessor(db_manager, tenant_manager)

        result = await tool_accessor._mission_service.get_staging_instructions(
            job_id=cli_mode_context["orchestrator_id"],
            tenant_key=cli_mode_context["tenant_key"],
        )

        assert "error" not in result

        assert "cli_mode_rules" in result
        assert "multi_agent_example" in result["cli_mode_rules"]
        example = result["cli_mode_rules"]["multi_agent_example"]
        assert "scenario" in example
        assert "agent_1" in example
        assert "agent_2" in example

    async def test_multi_terminal_mode_excludes_cli_mode_rules(
        self,
        db_manager: DatabaseManager,
        multi_terminal_context: dict,
    ):
        from giljo_mcp.tenant import TenantManager
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        tenant_manager = TenantManager()
        tool_accessor = ToolAccessor(db_manager, tenant_manager)

        result = await tool_accessor._mission_service.get_staging_instructions(
            job_id=multi_terminal_context["orchestrator_id"],
            tenant_key=multi_terminal_context["tenant_key"],
        )

        assert "error" not in result, f"Unexpected error: {result.get('message')}"

        assert "cli_mode_rules" not in result, "Multi-terminal mode should NOT include cli_mode_rules"
        assert "spawning_examples" not in result, "Multi-terminal mode should NOT include spawning_examples"

    async def test_cli_mode_rules_agent_display_name_usage_mentions_template_name(
        self,
        db_manager: DatabaseManager,
        cli_mode_context: dict,
    ):
        from giljo_mcp.tenant import TenantManager
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        tenant_manager = TenantManager()
        tool_accessor = ToolAccessor(db_manager, tenant_manager)

        result = await tool_accessor._mission_service.get_staging_instructions(
            job_id=cli_mode_context["orchestrator_id"],
            tenant_key=cli_mode_context["tenant_key"],
        )

        cli_rules = result.get("cli_mode_rules", {})
        agent_display_name_usage = cli_rules.get("agent_display_name_usage", "")

        assert "template" in agent_display_name_usage.lower(), "agent_display_name_usage should mention template"
        assert "unique" in agent_display_name_usage.lower(), (
            "agent_display_name_usage should emphasize uniqueness per agent instance"
        )

    async def test_cli_mode_rules_task_tool_mapping_mentions_subagent_type(
        self,
        db_manager: DatabaseManager,
        cli_mode_context: dict,
    ):
        from giljo_mcp.tenant import TenantManager
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        tenant_manager = TenantManager()
        tool_accessor = ToolAccessor(db_manager, tenant_manager)

        result = await tool_accessor._mission_service.get_staging_instructions(
            job_id=cli_mode_context["orchestrator_id"],
            tenant_key=cli_mode_context["tenant_key"],
        )

        cli_rules = result.get("cli_mode_rules", {})
        task_mapping = cli_rules.get("task_tool_mapping", "")

        assert "subagent_type" in task_mapping or "Task" in task_mapping, (
            "task_tool_mapping should mention Task tool or subagent_type"
        )
