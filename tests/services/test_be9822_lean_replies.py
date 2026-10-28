# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.product_crew import seed_product_crew
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.giljo_guide import build_giljo_guide


GUIDE_MAX = 18_300
STAGING_MAX = 23_863 * 3 // 4
ORCH_MISSION_MAX = 25_025 * 3 // 4
WORKER_MISSION_MAX = 10_200

CODEX_TOOL_OUTPUT_TOKEN_LIMIT = 10_000
CODEX_CHARS_PER_TOKEN = 42_693 / 11_068


def _chars(payload: dict) -> int:
    return len(json.dumps(payload, indent=2, ensure_ascii=False))


def _codex_tokens(payload: dict) -> float:
    return 2 * _chars(payload) / CODEX_CHARS_PER_TOKEN


def _wire(obj) -> dict:
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj


async def _render_all(db_session, db_manager, test_product, test_project) -> dict:
    tenant = test_project.tenant_key
    test_product.tenant_key = tenant
    await db_session.commit()
    await seed_product_crew(db_session, tenant, str(test_product.id))
    await ensure_default_types_seeded(db_session, tenant)
    test_project.product_id = test_product.id
    test_project.execution_mode = "subagent"
    await db_session.commit()

    job = AgentJob(
        job_id=str(uuid4()),
        job_type="orchestrator",
        tenant_key=tenant,
        project_id=test_project.id,
        mission="Orchestrate the project",
        status="active",
        job_metadata={"user_id": str(uuid4())},
    )
    db_session.add(job)
    await db_session.commit()
    db_session.add(
        AgentExecution(
            agent_id=str(uuid4()),
            job_id=job.job_id,
            tenant_key=tenant,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
            project_phase="staging",
        )
    )
    await db_session.commit()

    svc = OrchestrationService(
        db_manager=db_manager, tenant_manager=TenantManager(), test_session=db_session, websocket_manager=AsyncMock()
    )
    staging = _wire(
        await svc._mission.get_staging_instructions(
            job_id=job.job_id, tenant_key=tenant, detected_harness="claude-code"
        )
    )
    spawned = _wire(
        await svc.spawn_job(
            agent_display_name="implementer",
            agent_name="implementer",
            mission="Goal: add slugify(text) to the textkit package, with tests, and update the README usage line.",
            project_id=test_project.id,
            tenant_key=tenant,
        )
    )
    test_project.staging_status = "staging_complete"
    test_project.implementation_launched_at = datetime.now(UTC)
    await db_session.commit()

    orch = _wire(
        await svc._mission.get_agent_mission(job_id=job.job_id, tenant_key=tenant, detected_harness="claude-code")
    )
    worker = _wire(
        await svc._mission.get_agent_mission(
            job_id=spawned["job_id"], tenant_key=tenant, detected_harness="claude-code"
        )
    )
    return {"tenant": tenant, "staging": staging, "orch": orch, "worker": worker}




def test_guide_default_reply_is_at_most_half_of_master():
    size = _chars(build_giljo_guide())
    assert size <= GUIDE_MAX, f"get_giljo_guide is {size} chars; ceiling {GUIDE_MAX} (master 36,576)"


@pytest.mark.asyncio
async def test_four_replies_fit_their_ceilings(db_session, db_manager, test_product, test_project):
    r = await _render_all(db_session, db_manager, test_product, test_project)
    sizes = {name: _chars(r[name]) for name in ("staging", "orch", "worker")}
    assert sizes["staging"] <= STAGING_MAX, sizes
    assert sizes["orch"] <= ORCH_MISSION_MAX, sizes
    assert sizes["worker"] <= WORKER_MISSION_MAX, sizes


@pytest.mark.asyncio
async def test_worker_mission_fits_under_the_codex_output_limit_with_room(
    db_session, db_manager, test_product, test_project
):
    r = await _render_all(db_session, db_manager, test_product, test_project)
    tokens = _codex_tokens(r["worker"])
    assert tokens <= 0.6 * CODEX_TOOL_OUTPUT_TOKEN_LIMIT, f"~{tokens:.0f} Codex tokens"




@pytest.mark.asyncio
async def test_worker_is_enrolled_on_its_thread_by_its_first_mission_fetch(
    db_session, db_manager, test_product, test_project
):
    r = await _render_all(db_session, db_manager, test_product, test_project)
    worker = r["worker"]
    rows = await db_session.execute(
        select(CommParticipant.participant_id, CommParticipant.role, CommParticipant.harness).where(
            CommParticipant.tenant_key == r["tenant"],
            CommParticipant.thread_id == worker["thread_id"],
        )
    )
    found = {pid: (role, harness) for pid, role, harness in rows.all()}
    assert worker["agent_id"] in found, f"worker not enrolled; participants {sorted(found)}"
    role, harness = found[worker["agent_id"]]
    assert role != "auto-enrolled", "enrolled by the broadcast rescue, not the mission fetch"
    assert harness == "claude-code", f"the roster must name the session's harness, got {harness!r}"
    assert "Call `join_thread(" not in worker["full_protocol"], "the protocol still spends a call on join_thread"


@pytest.mark.asyncio
async def test_staging_does_not_spend_a_call_on_health_check(db_session, db_manager, test_product, test_project):
    from giljo_mcp.tools.tool_accessor._project_tools import _staging_start_instruction

    r = await _render_all(db_session, db_manager, test_product, test_project)
    protocol = json.dumps(r["staging"]["orchestrator_protocol"])
    assert "health_check()" not in protocol
    assert "health_check" not in _staging_start_instruction("job-1", is_chain_member=False)
    assert "health_check" not in _staging_start_instruction("job-1", is_chain_member=True)


def test_staging_copy_prompts_do_not_ask_for_health_check():
    from unittest.mock import MagicMock

    from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder

    project = MagicMock()
    project.id = "proj-9822"
    project.name = "BE-9822 probe"
    project.description = "d"
    project.mission = ""
    project.taxonomy_alias = "BE-9822"
    product = MagicMock()
    product.name = "p"
    builder = StagingPromptBuilder()
    for tool in ("claude-code", "codex", "multi_terminal"):
        staging = builder.build_staging_prompt(
            project=project,
            product=product,
            orchestrator_id="job-9822",
            project_id="proj-9822",
            agent_id="agent-9822",
            mcp_url="http://localhost:7272/mcp",
            tool=tool,
        )
        assert "health_check()" not in staging, tool
        assert "get_staging_instructions(job_id='job-9822')" in staging, tool
        thin = builder.build_thin_prompt(
            orchestrator_id="job-9822",
            agent_id="agent-9822",
            project_id="proj-9822",
            project=project,
            product=product,
            tool=tool,
            field_toggles={},
            depth_config={},
        )
        assert "health_check()" not in thin, tool
        assert "verifying MCP connection" not in thin, tool
        assert thin.index("1. Fetch complete context: get_staging_instructions('job-9822')") > 0, tool




@pytest.mark.asyncio
async def test_every_lifecycle_step_is_still_instructed(db_session, db_manager, test_product, test_project):
    r = await _render_all(db_session, db_manager, test_product, test_project)
    staging = json.dumps(r["staging"]["orchestrator_protocol"]) + r["staging"]["orchestrator_identity"]
    for call in ("get_context(", "update_project_mission(", "spawn_job(", "report_progress(", "complete_job("):
        assert call in staging, call

    orch = r["orch"]["full_protocol"]
    order = [orch.find("complete_job(job_id="), orch.find("write_project_closeout(")]
    assert -1 not in order and order == sorted(order), f"closeout order lost: {order}"
    orch += r["orch"]["agent_identity"]
    for needle in (
        "get_agent_result(",
        "finalize_job(",
        "report_progress(",
        "spawn_job(",
        "HANDOFF <TSK-id>:",
        "OPEN <TSK-id>:",
        "END-OF-PROTOCOL",
    ):
        assert needle in orch, needle

    worker = r["worker"]["full_protocol"]
    job_id = r["worker"]["job_id"]
    for needle in (
        f'report_progress(job_id="{job_id}"',
        f'complete_job(job_id="{job_id}"',
        f'set_agent_status(job_id="{job_id}", status="blocked"',
        f'get_thread_history(thread_id="{r["worker"]["thread_id"]}"',
        "HANDOFF <TSK-id>:",
        "OPEN <TSK-id>:",
        "Never call `finalize_job`",
        "END-OF-PROTOCOL",
    ):
        assert needle in worker, needle
    assert r["worker"]["next_required_actions"], "BE-9083 checklist dropped"


def test_guide_still_routes_the_whole_lifecycle():
    guide = build_giljo_guide()["guide"]
    for needle in (
        "stage_project(",
        "get_staging_instructions",
        "launch_implementation(",
        "get_implementation_prompt(",
        "get_job_mission",
        "complete_job",
        "write_project_closeout",
        "update_project(status='completed')",
        "## Verify before trusting",
        "PRODUCT_AMBIGUOUS",
        "Edition Scope",
        "link_projects(",
        "promote_task_to_project(",
    ):
        assert needle in guide, needle
