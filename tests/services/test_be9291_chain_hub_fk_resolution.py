# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.repositories._comm_thread_chain_hub_mixin import CommThreadChainHubMixin as RepoChainHubMixin
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services import mission_orchestration_service
from giljo_mcp.services._comm_thread_chain_hub_mixin import CommThreadChainHubMixin as ServiceChainHubMixin
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.conductor_staging_builder import resolve_conductor_early_return
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

_JAN = datetime(2026, 1, 1, tzinfo=UTC)
_FEB = datetime(2026, 2, 1, tzinfo=UTC)

_RUN = "0f7c1d2e-9a41-4b8e-8c33-5a6b7c8d9e01"
_OTHER_RUN = "1a2b3c4d-5e6f-4071-8899-aabbccddeeff"


def _svc(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_run(db_session, tenant: str, run_id: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        await db_session.execute(
            text(
                "INSERT INTO sequence_runs "
                "(id, tenant_key, project_ids, resolved_order, current_index, execution_mode, status, "
                " review_policy, project_statuses) "
                "VALUES (:id, :tk, '[]'::jsonb, '[]'::jsonb, 0, 'multi_terminal', 'running', "
                " 'per_card', '{}'::jsonb)"
            ),
            {"id": run_id, "tk": tenant},
        )
        await db_session.flush()


async def _seed_thread(db_session, tenant, tid, serial, subject, created, run_id=None) -> None:
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text(
                "INSERT INTO comm_threads (id, tenant_key, serial, subject, status, created_at, sequence_run_id) "
                "VALUES (:id, :tk, :s, :subj, 'open', :created, :run)"
            ),
            {"id": tid, "tk": tenant, "s": serial, "subj": subject, "created": created, "run": run_id},
        )
        await db_session.flush()




async def test_hub_resolves_by_fk_when_subject_omits_the_run_id(db_manager, db_session):
    tenant = "tk_be9291_fk_only"
    await _seed_run(db_session, tenant, _RUN)
    subject = "Chain: ship the widget"
    assert _RUN not in subject, "the premise of this test is a subject that cannot be substring-matched"
    await _seed_thread(db_session, tenant, "t_hub", 900, subject, _JAN, run_id=_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out is not None, "the hub must be discoverable without the run_id in its subject"
    assert out["thread_id"] == "t_hub"
    assert out["sequence_run_id"] == _RUN


async def test_legacy_subject_search_finds_nothing_and_raises_nothing(db_manager, db_session):
    tenant = "tk_be9291_silent"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_hub", 901, "Chain: ship the widget", _JAN, run_id=_RUN)

    legacy = await _svc(db_manager, db_session).search_threads(query=_RUN, tenant_key=tenant)

    assert legacy["threads"] == [], "substring discovery finds nothing here — and says so by staying quiet"




async def test_legacy_subject_hub_still_resolves_without_the_fk(db_manager, db_session):
    tenant = "tk_be9291_legacy"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_legacy", 902, f"Chain: old thing - run {_RUN}", _JAN, run_id=None)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out is not None and out["thread_id"] == "t_legacy"


async def test_fk_wins_over_a_subject_match(db_manager, db_session):
    tenant = "tk_be9291_precedence"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_decoy", 903, f"chatter about run {_RUN}", _JAN, run_id=None)
    await _seed_thread(db_session, tenant, "t_hub", 904, "Chain: ship the widget", _FEB, run_id=_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out["thread_id"] == "t_hub", "an FK-linked hub outranks any subject mention"


async def test_no_hub_returns_none_rather_than_a_wrong_thread(db_manager, db_session):
    tenant = "tk_be9291_absent"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_run(db_session, tenant, _OTHER_RUN)
    await _seed_thread(db_session, tenant, "t_other", 905, "Chain: someone else", _JAN, run_id=_OTHER_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out is None


async def test_a_soft_deleted_hub_is_not_resolved(db_manager, db_session):
    tenant = "tk_be9291_deleted"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_gone", 906, "Chain: ship the widget", _JAN, run_id=_RUN)
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text("UPDATE comm_threads SET deleted_at = now() WHERE id = 't_gone' AND tenant_key = :tk"),
            {"tk": tenant},
        )
        await db_session.flush()

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out is None


async def test_another_tenants_hub_is_never_resolved(db_manager, db_session):
    mine, theirs = "tk_be9291_mine", "tk_be9291_theirs"
    await _seed_run(db_session, theirs, _RUN)
    await _seed_thread(db_session, theirs, "t_theirs", 907, "Chain: not yours", _JAN, run_id=_RUN)
    await _seed_run(db_session, mine, _OTHER_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=mine)

    assert out is None, "a hub in another tenant must not resolve, FK match or not"




async def test_create_thread_stamps_the_run_and_the_hub_is_then_discoverable(db_manager, db_session):
    tenant = "tk_be9291_create"
    await _seed_run(db_session, tenant, _RUN)
    svc = _svc(db_manager, db_session)

    created = await svc.create_thread(subject="Chain: ship the widget", sequence_run_id=_RUN, tenant_key=tenant)

    assert created["sequence_run_id"] == _RUN, "the link is stamped at birth, not derived from the subject"
    found = await svc.resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)
    assert found is not None and found["thread_id"] == created["thread_id"]


async def test_create_thread_rejects_a_run_id_that_is_not_a_run_here(db_manager, db_session):
    tenant = "tk_be9291_badrun"
    await _seed_run(db_session, tenant, _RUN)
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError):
        await svc.create_thread(subject="Chain: bogus", sequence_run_id=_OTHER_RUN, tenant_key=tenant)


async def test_create_thread_rejects_another_tenants_run_id(db_manager, db_session):
    mine, theirs = "tk_be9291_cmine", "tk_be9291_ctheirs"
    await _seed_run(db_session, theirs, _RUN)
    await _seed_run(db_session, mine, _OTHER_RUN)
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError):
        await svc.create_thread(subject="Chain: reaching over", sequence_run_id=_RUN, tenant_key=mine)


async def test_create_thread_refuses_a_second_hub_and_names_the_first(db_manager, db_session):
    tenant = "tk_be9291_second_hub"
    await _seed_run(db_session, tenant, _RUN)
    svc = _svc(db_manager, db_session)
    first = await svc.create_thread(subject="Chain: ship the widget", sequence_run_id=_RUN, tenant_key=tenant)

    with pytest.raises(ValidationError) as caught:
        await svc.create_thread(subject="Chain: ship the widget", sequence_run_id=_RUN, tenant_key=tenant)

    assert first["thread_id"] in str(caught.value), (
        "the refusal must name the hub that already exists — a restaged conductor "
        "adopts it, and an unnamed refusal would strand it"
    )
    found = await svc.resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)
    assert found["thread_id"] == first["thread_id"], "the surviving hub is still THE hub"


async def test_a_second_hub_is_allowed_once_the_first_is_soft_deleted(db_manager, db_session):
    tenant = "tk_be9291_replace_hub"
    await _seed_run(db_session, tenant, _RUN)
    svc = _svc(db_manager, db_session)
    first = await svc.create_thread(subject="Chain: ship the widget", sequence_run_id=_RUN, tenant_key=tenant)
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text("UPDATE comm_threads SET deleted_at = now() WHERE id = :id"),
            {"id": first["thread_id"]},
        )
        await db_session.flush()

    replacement = await svc.create_thread(subject="Chain: ship the widget", sequence_run_id=_RUN, tenant_key=tenant)

    assert replacement["sequence_run_id"] == _RUN
    found = await svc.resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)
    assert found["thread_id"] == replacement["thread_id"]


async def test_another_tenants_hub_does_not_block_creation(db_manager, db_session):
    mine, theirs = "tk_be9291_hmine", "tk_be9291_htheirs"
    await _seed_run(db_session, mine, _RUN)
    await _seed_run(db_session, theirs, _OTHER_RUN)
    svc = _svc(db_manager, db_session)
    await _seed_thread(db_session, theirs, "t_their_hub", 8801, "Chain: theirs", _JAN, run_id=_OTHER_RUN)

    created = await svc.create_thread(subject="Chain: mine", sequence_run_id=_RUN, tenant_key=mine)

    assert created["sequence_run_id"] == _RUN


async def test_a_plain_thread_is_unaffected(db_manager, db_session):
    tenant = "tk_be9291_plain"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)

    created = await _svc(db_manager, db_session).create_thread(subject="just a chat", tenant_key=tenant)

    assert created["sequence_run_id"] is None


async def test_purging_the_run_unlinks_the_hub_instead_of_deleting_it(db_manager, db_session):
    tenant = "tk_be9291_purge"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_hub", 908, "Chain: ship the widget", _JAN, run_id=_RUN)

    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            text("DELETE FROM sequence_runs WHERE id = :r AND tenant_key = :tk"), {"r": _RUN, "tk": tenant}
        )
        await db_session.flush()
        row = (
            await db_session.execute(
                text("SELECT sequence_run_id FROM comm_threads WHERE id = 't_hub' AND tenant_key = :tk"),
                {"tk": tenant},
            )
        ).first()

    assert row is not None, "purging the run must NOT delete the hub thread"
    assert row[0] is None, "the link is cleared, not cascaded"




def test_the_repository_serves_hub_resolution_by_identity():
    assert CommThreadRepository.resolve_chain_hub_thread is RepoChainHubMixin.resolve_chain_hub_thread
    assert CommThreadRepository._require_sequence_run is RepoChainHubMixin._require_sequence_run


def test_the_service_serves_hub_resolution_by_identity():
    assert CommThreadService.resolve_chain_hub_thread is ServiceChainHubMixin.resolve_chain_hub_thread


def test_the_service_serves_the_conductor_resolver_by_identity():
    assert mission_orchestration_service.resolve_conductor_early_return is resolve_conductor_early_return


async def test_the_conductor_branch_is_served_by_the_extracted_resolver(monkeypatch):
    svc = MissionOrchestrationService(db_manager=None, tenant_manager=TenantManager())  # type: ignore[arg-type]

    class _Job:
        job_type = "orchestrator"
        project_id = None

    class _Execution:
        agent_id = "be9291-conductor-agent"
        job = _Job()

    class _Repo:
        async def get_execution_with_job(self, session, tenant_key, job_id):
            return _Execution()

    svc._repo = _Repo()  # type: ignore[assignment]

    sentinel = {"__served_by__": "_build_conductor_early_return"}
    calls: list[dict] = []

    async def _fake(session, *, chain, repo, execution, job_id, tenant_key, preset):
        calls.append({"job_id": job_id, "tenant_key": tenant_key})
        return sentinel

    monkeypatch.setattr(mission_orchestration_service, "resolve_conductor_early_return", _fake)

    ctx = await svc._build_orchestrator_context(None, "job-be9291", "tk_be9291_pin")

    assert calls == [{"job_id": "job-be9291", "tenant_key": "tk_be9291_pin"}], (
        "the conductor branch did not delegate — it was re-inlined and the extracted method is dead"
    )
    assert ctx == {"early_return": sentinel}
