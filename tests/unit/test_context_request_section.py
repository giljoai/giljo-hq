# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentTemplate
from tests.helpers.product_crew_helper import seed_crew


class TestContextRequestSection:

    @pytest.mark.asyncio
    async def test_context_request_in_full_protocol(self, db_session: AsyncSession):
        from giljo_mcp.services.protocol_builder import _generate_agent_protocol

        protocol = _generate_agent_protocol(job_id="test-job", tenant_key="test-tenant", agent_name="implementer")
        assert "REQUEST_CONTEXT:" in protocol, "full_protocol should contain REQUEST_CONTEXT prefix"
        assert "Requesting Broader Context" in protocol, "full_protocol should contain context request guidance"

    @pytest.mark.asyncio
    async def test_system_instructions_has_slim_bootstrap(self, db_session: AsyncSession):
        tenant_key = "test_tenant_context_0813"

        _product, _names = await seed_crew(db_session, tenant_key)
        count = len(_names)
        assert count == 5, "Should seed 5 default templates (orchestrator is system-managed)"

        with tenant_session_context(db_session, tenant_key):
            result = await db_session.execute(select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
            templates = result.scalars().all()

        for template in templates:
            system_inst = template.system_instructions
            assert "get_job_mission" in system_inst, f"{template.role} bootstrap should reference get_job_mission"
            assert "full_protocol" in system_inst, f"{template.role} bootstrap should reference full_protocol"
            assert "REQUESTING BROADER CONTEXT" not in system_inst, (
                f"{template.role} should not have context request section in bootstrap"
            )

    @pytest.mark.asyncio
    async def test_full_protocol_has_messaging_prefixes(self, db_session: AsyncSession):
        from giljo_mcp.services.protocol_builder import _generate_agent_protocol

        protocol = _generate_agent_protocol(job_id="test-job", tenant_key="test-tenant", agent_name="tester")
        assert "BLOCKER:" in protocol
        assert "PROGRESS:" in protocol
        assert "COMPLETE:" in protocol
        assert "READY:" in protocol
        assert "REQUEST_CONTEXT:" in protocol

    @pytest.mark.asyncio
    async def test_full_protocol_has_context_request_specificity_guidance(self, db_session: AsyncSession):
        from giljo_mcp.services.protocol_builder import _generate_agent_protocol

        protocol = _generate_agent_protocol(job_id="test-job", tenant_key="test-tenant", agent_name="analyzer")
        assert "specific" in protocol.lower() or "REQUEST_CONTEXT:" in protocol

    @pytest.mark.asyncio
    async def test_full_protocol_instructs_wait_for_response(self, db_session: AsyncSession):
        from giljo_mcp.services.protocol_builder import _generate_agent_protocol

        protocol = _generate_agent_protocol(job_id="test-job", tenant_key="test-tenant", agent_name="implementer")
        assert "get_thread_history" in protocol
        assert "wait" in protocol.lower() or "Wait" in protocol

    @pytest.mark.asyncio
    async def test_full_protocol_has_send_message_for_context(self, db_session: AsyncSession):
        from giljo_mcp.services.protocol_builder import _generate_agent_protocol

        protocol = _generate_agent_protocol(job_id="test-job", tenant_key="test-tenant", agent_name="documenter")
        assert "post_to_thread" in protocol

    @pytest.mark.asyncio
    async def test_full_protocol_warns_against_guessing(self, db_session: AsyncSession):
        from giljo_mcp.services.protocol_builder import _generate_agent_protocol

        protocol = _generate_agent_protocol(job_id="test-job", tenant_key="test-tenant", agent_name="reviewer")
        assert "guess" in protocol.lower() or "Do NOT guess" in protocol

    def test_orchestrator_response_instructions(self):
        from giljo_mcp.template_seeder import _get_orchestrator_context_response_section

        response_section = _get_orchestrator_context_response_section()

        assert "RESPONDING TO CONTEXT REQUESTS" in response_section, (
            "Orchestrator missing RESPONDING TO CONTEXT REQUESTS section"
        )
        assert "CONTEXT_RESPONSE:" in response_section, "Orchestrator should show CONTEXT_RESPONSE message format"
        assert "filtered excerpt" in response_section.lower(), (
            "Orchestrator should mention providing filtered excerpts, not full text"
        )

    @pytest.mark.asyncio
    async def test_non_orchestrator_agents_lack_response_section(self, db_session: AsyncSession):
        tenant_key = "test_tenant_non_orch"

        await seed_crew(db_session, tenant_key)

        with tenant_session_context(db_session, tenant_key):
            result = await db_session.execute(
                select(AgentTemplate).where(
                    AgentTemplate.tenant_key == tenant_key,
                    AgentTemplate.role != "orchestrator",
                )
            )
            non_orchestrator_templates = result.scalars().all()

        for template in non_orchestrator_templates:
            user_inst = template.user_instructions
            assert "RESPONDING TO CONTEXT REQUESTS" not in user_inst, (
                f"{template.role} should not have orchestrator-specific response instructions"
            )

