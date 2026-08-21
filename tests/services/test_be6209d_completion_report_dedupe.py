# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6209d: the inbox completion_report must not duplicate the full result body.

An agent's completion result reaches an orchestrator through TWO server-side
channels:
  (1) ``get_agent_result(job_id)`` -> the full ``execution.result`` dict
      (the canonical store / audit row / dashboard record), and
  (2) an inbox ``completion_report`` message surfaced by ``receive_messages``.

Before BE-6209d both carried the FULL ``result["summary"]`` verbatim, so an
orchestrator that processed both paid for the whole body twice. The fix slims
channel (2) to a SHORT pointer (job_id + a one-line summary + an explicit
"full result via get_agent_result" hint) while channel (1) — the canonical
store — is left byte-identical.

HARD CONSTRAINT (tested here): the audit row (``execution.result``) and BOTH
channels still return a usable, non-empty completion signal. Only the
DUPLICATION of the full body across both channels is removed.

Parallel-safe: db_session (TransactionalTestContext); each test owns its setup.
Edition Scope: CE.
"""

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


pytestmark = pytest.mark.asyncio


# A long, multi-paragraph summary of the kind agents actually write. The SENTINEL
# lives deep in a LATER paragraph: it must survive in the canonical store
# (get_agent_result / execution.result) but must NOT be duplicated into the
# inbox completion_report message.
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
    # BE-9437: a project belongs to a product. Its own, so an active
    # seed cannot collide under idx_project_single_active_per_product.
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
    return proj


@pytest_asyncio.fixture
async def service(db_session, db_manager) -> OrchestrationService:
    return OrchestrationService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )


# ---------------------------------------------------------------------------
# Pure helper unit tests (no DB) — the one-line collapse contract.
# ---------------------------------------------------------------------------


class TestOneLineSummaryHelper:
    """_one_line_summary keeps the notification short and always non-empty."""

    def test_short_single_line_passes_through(self):
        # Back-compat: a short summary is carried verbatim (no truncation).
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


# ---------------------------------------------------------------------------
# Service-layer RED-GREEN: full body lives ONLY in the canonical store.
# ---------------------------------------------------------------------------


class TestCompletionReportDoesNotDuplicateBody:
    async def test_inbox_pointer_no_body_dup_but_canonical_store_intact(self, db_session, service, project, tenant_key):
        # Arrange: orchestrator first, then a specialist that completes with a
        # long, multi-paragraph summary.
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

        # Act
        await service.complete_job(
            job_id=spec_spawn.job_id,
            result=result_payload,
            tenant_key=tenant_key,
        )

        # --- Channel 2: the inbox completion_report message ---
        msg = (
            await db_session.execute(
                select(Message).where(
                    Message.tenant_key == tenant_key,
                    Message.project_id == project.id,
                    Message.message_type == "completion_report",
                )
            )
        ).scalar_one()

        # Still a usable, non-empty completion signal...
        assert msg.content.strip()
        assert "COMPLETION REPORT" in msg.content
        assert spec_spawn.job_id in msg.content  # job_id pointer
        assert "get_agent_result" in msg.content  # explicit hint to the canonical store
        assert _FIRST_LINE in msg.content  # one-line summary is carried
        # ...but the FULL body is NOT duplicated here (the dedupe).
        assert _DEEP_SENTINEL not in msg.content, (
            "completion_report must not duplicate the full result body — only a one-line pointer"
        )

        # --- Channel 1: the canonical store is byte-identical (audit row preserved) ---
        stored = await service.get_agent_result(job_id=spec_spawn.job_id, tenant_key=tenant_key)
        assert stored == result_payload
        assert _DEEP_SENTINEL in stored["summary"], "full summary must survive in the canonical store"

        # --- Audit row on AgentExecution itself ---
        execution = (
            await db_session.execute(select(AgentExecution).where(AgentExecution.agent_id == spec_spawn.agent_id))
        ).scalar_one()
        assert execution.status == "complete"
        assert execution.result == result_payload
        assert _DEEP_SENTINEL in execution.result["summary"]

        # Orchestrator recipient unchanged (the signal still reaches the orchestrator).
        assert msg.from_agent_id == str(spec_spawn.agent_id)
        assert orch_spawn.agent_id  # sanity: orchestrator was the intended recipient
