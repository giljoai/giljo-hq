# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models import AgentExecution, AgentTemplate, Message, Product, Project
from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.tenant import TenantManager
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio


_DEEP_SENTINEL = "ZZZ_DEEP_BODY_SENTINEL_must_not_be_duplicated"
_FIRST_LINE = "Implemented the chain dedupe and added a regression test."
_LONG_SUMMARY = (
    f"{_FIRST_LINE}\n"
    "\n"
    "Details: refactored the completion side-effect path, slimmed the inbox\n"
    "notification to a pointer, and verified the canonical store is untouched.\n"
    "\n"
    f"Decisions: {_DEEP_SENTINEL}. Validated locally with pytest at the service layer.\n"
)


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def agent_templates(db_session, tenant_key):
    for name in ("specialist-1", "orchestrator"):
        db_session.add(
            AgentTemplate(
                tenant_key=tenant_key,
                name=name,
                role=name,
                description=f"Test template for {name}",
                system_instructions=f"# {name}\nTest agent.",
                is_active=True,
            )
        )
    await db_session.commit()


@pytest_asyncio.fixture
async def project(db_session, tenant_key, agent_templates) -> Project:
    _owning_product_proj = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_proj)
    proj = Project(
        id=str(uuid.uuid4()),
        name="BE-6209d completion dedupe project",
        description="Service-layer regression for completion-report dedupe",
        mission="Dedupe the two server-side completion-signal copies",
        status="active",
        tenant_key=tenant_key,
        product_id=_owning_product_proj.id,
        execution_mode="multi_terminal",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    await adopt_all_templates(db_session, tenant_key, _owning_product_proj.id)
    return proj


@pytest_asyncio.fixture
async def service(db_session, db_manager) -> OrchestrationService:
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )




class TestOneLineSummaryHelper:

    def test_short_single_line_passes_through(self):
        out = OrchestrationAgentStateService._one_line_summary("Refactored the auth module")
        assert out == "Refactored the auth module"

    def test_multiline_collapses_to_first_nonblank_line(self):
        out = OrchestrationAgentStateService._one_line_summary(_LONG_SUMMARY)
        assert out == _FIRST_LINE
        assert _DEEP_SENTINEL not in out

    def test_long_line_is_truncated_with_ellipsis(self):
        out = OrchestrationAgentStateService._one_line_summary("x" * 500)
        assert len(out) <= 200
        assert out.endswith("...")

    @pytest.mark.parametrize("bad", [None, "", "   ", "\n\n"])
    def test_missing_or_blank_degrades_to_placeholder(self, bad):
        assert OrchestrationAgentStateService._one_line_summary(bad) == "Work completed"




class TestCompletionReportDoesNotDuplicateBody:
    async def test_inbox_pointer_no_body_dup_but_canonical_store_intact(self, db_session, service, project, tenant_key):
        orch_spawn = await service.spawn_job(
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            mission="Orchestrate the project",
            project_id=project.id,
            tenant_key=tenant_key,
        )
        spec_spawn = await service.spawn_job(
            agent_display_name="specialist",
            agent_name="specialist-1",
            mission="Do specialized work",
            project_id=project.id,
            tenant_key=tenant_key,
        )

        result_payload = {
            "summary": _LONG_SUMMARY,
            "artifacts": ["src/feature.py"],
            "commits": ["abc123"],
        }

        await service.complete_job(
            job_id=spec_spawn.job_id,
            result=result_payload,
            tenant_key=tenant_key,
        )

        msg = (
            await db_session.execute(
                select(Message).where(
                    Message.tenant_key == tenant_key,
                    Message.project_id == project.id,
                    Message.message_type == "completion_report",
                )
            )
        ).scalar_one()

        assert msg.content.strip()
        assert "COMPLETION REPORT" in msg.content
        assert spec_spawn.job_id in msg.content
        assert "get_agent_result" in msg.content
        assert _FIRST_LINE in msg.content
        assert _DEEP_SENTINEL not in msg.content, (
            "completion_report must not duplicate the full result body — only a one-line pointer"
        )

        stored = await service.get_agent_result(job_id=spec_spawn.job_id, tenant_key=tenant_key)
        assert stored == result_payload
        assert _DEEP_SENTINEL in stored["summary"], "full summary must survive in the canonical store"

        execution = (
            await db_session.execute(select(AgentExecution).where(AgentExecution.agent_id == spec_spawn.agent_id))
        ).scalar_one()
        assert execution.status == "complete"
        assert execution.result == result_payload
        assert _DEEP_SENTINEL in execution.result["summary"]

        assert msg.from_agent_id == str(spec_spawn.agent_id)
        assert orch_spawn.agent_id
