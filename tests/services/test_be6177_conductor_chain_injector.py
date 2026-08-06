# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6177 (Bug 4) — runtime conductor chain-drive injection regression.

The runtime orchestrator protocol returned by get_job_mission is built by the
chain-BLIND _generate_agent_protocol. A conductor orchestrator in the IMPLEMENTATION
phase must still receive CH_CHAIN_DRIVE (its "advance the chain" instructions) at
runtime; inject_conductor_chain_drive resolves chain_ctx and appends the chain chapters
to mirror the staging path. This is the failing layer the alpha's live probe exposed
(get_job_mission returned the generic solo protocol with no CH_CHAIN_DRIVE).

It MUST be a no-op for solo / sub_orchestrator / non-orchestrator / not-yet-launched,
so the solo runtime protocol stays byte-identical (Deletion Test).

Edition Scope: CE.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.conductor_chain_injector import inject_conductor_chain_drive
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_BASE_PROTOCOL = "SOLO ORCHESTRATOR PROTOCOL — startup / coordination / closeout"


class _FakeJob:
    def __init__(self, project_id: str, *, job_type: str = "orchestrator", job_id: str = "job-head") -> None:
        self.job_type = job_type
        self.project_id = project_id
        self.job_id = job_id


class _FakeExec:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id


class _FakeProject:
    def __init__(self, *, launched: bool = True) -> None:
        self.implementation_launched_at = datetime.now(UTC) if launched else None


async def _seed_run(db_manager, *, resolved_order, conductor_agent_id, status="running") -> str:
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        session.add(
            SequenceRun(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                project_ids=resolved_order,
                resolved_order=resolved_order,
                current_index=0,
                execution_mode="claude_code_cli",
                status=status,
                locked=True,
                conductor_agent_id=conductor_agent_id,
                project_statuses=dict.fromkeys(resolved_order, "pending"),
            )
        )
        await session.commit()
    return tenant_key


def _svc(db_manager) -> MissionService:
    return MissionService(db_manager=db_manager, tenant_manager=TenantManager())


async def test_conductor_in_implementation_gets_chain_drive(db_manager):
    """A launched head-project conductor's runtime protocol gains CH_CHAIN_DRIVE."""
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(db_manager, resolved_order=[p1, p2], conductor_agent_id="cond-1")

    out = await inject_conductor_chain_drive(
        _svc(db_manager), _BASE_PROTOCOL, _FakeJob(p1), _FakeExec("cond-1"), _FakeProject(), tenant_key
    )

    assert "CH_CHAIN_DRIVE" in out
    assert _BASE_PROTOCOL in out  # base protocol preserved, chapters appended


async def test_not_launched_sub_orch_gets_ch_sub_orchestrator(db_manager):
    """§14 (BE-6206): a chain SUB-ORCHESTRATOR receives CH_SUB_ORCHESTRATOR on its FIRST
    fetch — BEFORE implementation_launched_at is stamped. The per-project launch gate was
    removed (the stamp now happens at the sub-orch's OWN staging-end), so the injector must
    no longer require a launched project for a project-bound chain member. RED before §14
    (the injector early-returned on implementation_launched_at IS NULL)."""
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(db_manager, resolved_order=[p1, p2], conductor_agent_id="cond-1")

    out = await inject_conductor_chain_drive(
        _svc(db_manager), _BASE_PROTOCOL, _FakeJob(p1), _FakeExec("sub-1"), _FakeProject(launched=False), tenant_key
    )

    assert "CH_SUB_ORCHESTRATOR" in out, "a not-yet-launched chain sub-orch must still get its combined chapter"
    assert "CH_CHAIN_DRIVE" not in out, "a sub-orch must NOT get the conductor drive chapters"
    assert _BASE_PROTOCOL in out, "base protocol preserved, chapter appended"
    assert "project 1 of 2" in out


async def test_sub_orch_runtime_gets_ch_sub_orchestrator(db_manager):
    """BE-6187: a sub_orchestrator's runtime protocol gains CH_SUB_ORCHESTRATOR (its
    chain position + Hub-thread discovery), NOT the conductor drive chapters."""
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(db_manager, resolved_order=[p1, p2], conductor_agent_id="cond-1")

    out = await inject_conductor_chain_drive(
        _svc(db_manager), _BASE_PROTOCOL, _FakeJob(p2), _FakeExec("sub-1"), _FakeProject(), tenant_key
    )

    assert "CH_SUB_ORCHESTRATOR" in out, "sub-orch must receive its chain-member chapter at runtime"
    assert "CH_CHAIN_DRIVE" not in out, "sub-orch must NOT get the conductor drive chapters"
    assert _BASE_PROTOCOL in out, "base protocol preserved, chapter appended"
    # Position 2 of 2 (p2 is index 1 in resolved_order) and the Hub discovery path.
    # BE-9291 DELIBERATELY CHANGED the probe: discovery moved off the run_id subject
    # substring onto the comm_threads.sequence_run_id FK, and the bare `search_threads`
    # name now survives here only as a ToolSearch bootstrap hint.
    assert "project 2 of 2" in out
    assert "hub_thread_id" in out


async def test_solo_no_active_run_is_noop(db_manager):
    """A project with no active sequence run renders byte-identical (Deletion Test)."""
    tenant_key = TenantManager.generate_tenant_key()
    out = await inject_conductor_chain_drive(
        _svc(db_manager), _BASE_PROTOCOL, _FakeJob(str(uuid.uuid4())), _FakeExec("solo-1"), _FakeProject(), tenant_key
    )

    assert out == _BASE_PROTOCOL


async def test_non_orchestrator_job_is_noop(db_manager):
    """A worker (non-orchestrator) job never injects chain chapters, even on the head."""
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(db_manager, resolved_order=[p1], conductor_agent_id="cond-1")

    out = await inject_conductor_chain_drive(
        _svc(db_manager),
        _BASE_PROTOCOL,
        _FakeJob(p1, job_type="implementer"),
        _FakeExec("cond-1"),
        _FakeProject(),
        tenant_key,
    )

    assert out == _BASE_PROTOCOL


# ---------------------------------------------------------------------------
# BE-6214: the override-first preamble (CH_CONDUCTOR_PREAMBLE / CH_SUBORCH_PREAMBLE) is
# REMOVED. The runtime injector now LEADS with the (lean-trimmed) base protocol, and the
# three seams (handed scope / escalate-to-conductor / advance-not-complete_job) live in
# the chain chapters (CH_CHAIN_DRIVE / CH_SUB_ORCHESTRATOR). No preamble is prepended.
# ---------------------------------------------------------------------------


async def test_conductor_injection_leads_with_chain_chapters(db_manager):
    """BE-9083a: a project-less conductor's runtime protocol LEADS with the chain
    chapters (CH_CAPABILITY + CH_CHAIN_DRIVE — the part harness tail-truncation must
    not eat) and the base solo protocol follows. The BE-6214 override-first preamble
    stays removed; the seams live in CH_CHAIN_DRIVE."""
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(db_manager, resolved_order=[p1, p2], conductor_agent_id="cond-1")

    out = await inject_conductor_chain_drive(
        _svc(db_manager), _BASE_PROTOCOL, _FakeJob(None, job_id="job-cond"), _FakeExec("cond-1"), None, tenant_key
    )

    assert "CH_CONDUCTOR_PREAMBLE" not in out, "BE-6214: the override-first preamble is removed"
    assert out.endswith(_BASE_PROTOCOL), "the base protocol must TRAIL the chain chapters (BE-9083a)"
    assert "CH_CHAIN_DRIVE" in out
    assert out.index("CH_CHAIN_DRIVE") < out.index(_BASE_PROTOCOL), "chain drive must precede the solo body"
    # Seam relocation: the handed-scope + advance-not-complete_job seams now live in the drive chapter.
    assert "SCOPE IS HANDED" in out
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in out


async def test_suborch_injection_leads_with_chain_chapter(db_manager):
    """BE-9083a: a sub-orchestrator's runtime protocol LEADS with CH_SUB_ORCHESTRATOR
    (the chain script truncation must not eat), then the base solo protocol; no
    conductor drive chapters. The BE-6214 preamble stays removed."""
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(db_manager, resolved_order=[p1, p2], conductor_agent_id="cond-1")

    out = await inject_conductor_chain_drive(
        _svc(db_manager), _BASE_PROTOCOL, _FakeJob(p2), _FakeExec("sub-1"), _FakeProject(), tenant_key
    )

    assert "CH_SUBORCH_PREAMBLE" not in out, "BE-6214: the override-first preamble is removed"
    assert out.endswith(_BASE_PROTOCOL), "the base protocol must TRAIL the chain chapter (BE-9083a)"
    assert "CH_SUB_ORCHESTRATOR" in out
    assert out.index("CH_SUB_ORCHESTRATOR") < out.index(_BASE_PROTOCOL), "chain chapter must precede the solo body"
    assert "SCOPE IS HANDED" in out, "the handed-scope seam now lives in CH_SUB_ORCHESTRATOR"
    assert "CH_CHAIN_DRIVE" not in out, "a sub-orch must NOT get the conductor drive chapters"
