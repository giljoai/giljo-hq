# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain-hub discovery resolves on a real FK, not a subject substring (BE-9291).

A chain hub used to be found by substring-searching its own SUBJECT for the run_id
(``search_threads(query="{run_id}")``), which made a free-text display field
load-bearing lookup machinery. When that broke, NOTHING errored: a sub-orchestrator
simply never found its hub and went quiet.

``comm_threads.sequence_run_id`` is that link made structural. Resolution follows the
``resolve_or_create_bound_thread`` precedence idiom:

  1. FK match on ``sequence_run_id``  -> that thread (subject irrelevant);
  2. otherwise the legacy subject substring, so a hub the backfill could not reach
     (or one a conductor created without stamping) still resolves instead of going
     silent again;
  3. nothing matches -> ``None``, an explicit absence the caller can act on.

THE test in this file is ``test_hub_resolves_by_fk_when_subject_omits_the_run_id``:
a hub whose subject contains no run_id at all. That is what proves discovery genuinely
moved off the string rather than merely gaining a second path to it.

Real DB (rollback-isolated ``db_session``), tenant-scoped (ADR-009).
"""

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

# A realistic run id. The point of every subject below is whether this string
# appears in it — so it is spelled out once and never interpolated by accident.
_RUN = "0f7c1d2e-9a41-4b8e-8c33-5a6b7c8d9e01"
_OTHER_RUN = "1a2b3c4d-5e6f-4071-8899-aabbccddeeff"


def _svc(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_run(db_session, tenant: str, run_id: str) -> None:
    """Insert a minimal sequence_runs row — the FK target."""
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


# ---------------------------------------------------------------------------
# The regression test that matters
# ---------------------------------------------------------------------------


async def test_hub_resolves_by_fk_when_subject_omits_the_run_id(db_manager, db_session):
    """A subject with NO run_id in it anywhere still resolves. This is the whole project.

    Before the FK existed this could not be done at all: the only handle on the hub was
    the substring, so a subject like this one was undiscoverable — silently.
    """
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
    """The silent failure, reproduced: the OLD mechanism returns an empty list, not an error.

    This is why the defect was invisible. Kept as a test because "it fails quietly" is the
    load-bearing fact about the mechanism being replaced — if this ever starts raising, the
    urgency of the FK path changes and someone should know.
    """
    tenant = "tk_be9291_silent"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_hub", 901, "Chain: ship the widget", _JAN, run_id=_RUN)

    legacy = await _svc(db_manager, db_session).search_threads(query=_RUN, tenant_key=tenant)

    assert legacy["threads"] == [], "substring discovery finds nothing here — and says so by staying quiet"


# ---------------------------------------------------------------------------
# Precedence + isolation
# ---------------------------------------------------------------------------


async def test_legacy_subject_hub_still_resolves_without_the_fk(db_manager, db_session):
    """A pre-migration hub the backfill could not reach must not become undiscoverable.

    Removing the substring dependency must not remove the substring TOLERANCE — that is
    the (a)-shaped answer to "what happens to rows already in the old shape".
    """
    tenant = "tk_be9291_legacy"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_thread(db_session, tenant, "t_legacy", 902, f"Chain: old thing - run {_RUN}", _JAN, run_id=None)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out is not None and out["thread_id"] == "t_legacy"


async def test_fk_wins_over_a_subject_match(db_manager, db_session):
    """Both present -> the FK decides. The structural link outranks the string, always."""
    tenant = "tk_be9291_precedence"
    await _seed_run(db_session, tenant, _RUN)
    # The decoy is OLDER, so "oldest wins" alone would pick it. Only FK precedence does not.
    await _seed_thread(db_session, tenant, "t_decoy", 903, f"chatter about run {_RUN}", _JAN, run_id=None)
    await _seed_thread(db_session, tenant, "t_hub", 904, "Chain: ship the widget", _FEB, run_id=_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out["thread_id"] == "t_hub", "an FK-linked hub outranks any subject mention"


async def test_no_hub_returns_none_rather_than_a_wrong_thread(db_manager, db_session):
    """No hub for this run -> None. Never another run's hub."""
    tenant = "tk_be9291_absent"
    await _seed_run(db_session, tenant, _RUN)
    await _seed_run(db_session, tenant, _OTHER_RUN)
    await _seed_thread(db_session, tenant, "t_other", 905, "Chain: someone else", _JAN, run_id=_OTHER_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)

    assert out is None


async def test_a_soft_deleted_hub_is_not_resolved(db_manager, db_session):
    """Soft-deleted threads are invisible to every other read here; discovery is no exception."""
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
    """Tenant isolation on the discovery path (ADR-009). A run id is not a capability."""
    mine, theirs = "tk_be9291_mine", "tk_be9291_theirs"
    await _seed_run(db_session, theirs, _RUN)
    await _seed_thread(db_session, theirs, "t_theirs", 907, "Chain: not yours", _JAN, run_id=_RUN)
    await _seed_run(db_session, mine, _OTHER_RUN)

    out = await _svc(db_manager, db_session).resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=mine)

    assert out is None, "a hub in another tenant must not resolve, FK match or not"


# ---------------------------------------------------------------------------
# Creation: the conductor stamps the link, and a bad id never reaches the FK
# ---------------------------------------------------------------------------


async def test_create_thread_stamps_the_run_and_the_hub_is_then_discoverable(db_manager, db_session):
    """The other half of the loop: what the conductor writes is what discovery reads.

    Deliberately created with a subject carrying NO run_id — a hub born the way step 5
    of this project lets conductors write them.
    """
    tenant = "tk_be9291_create"
    await _seed_run(db_session, tenant, _RUN)
    svc = _svc(db_manager, db_session)

    created = await svc.create_thread(subject="Chain: ship the widget", sequence_run_id=_RUN, tenant_key=tenant)

    assert created["sequence_run_id"] == _RUN, "the link is stamped at birth, not derived from the subject"
    found = await svc.resolve_chain_hub_thread(sequence_run_id=_RUN, tenant_key=tenant)
    assert found is not None and found["thread_id"] == created["thread_id"]


async def test_create_thread_rejects_a_run_id_that_is_not_a_run_here(db_manager, db_session):
    """An unknown run id is a 422 from the service, never a 500 from the constraint."""
    tenant = "tk_be9291_badrun"
    await _seed_run(db_session, tenant, _RUN)
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError):
        await svc.create_thread(subject="Chain: bogus", sequence_run_id=_OTHER_RUN, tenant_key=tenant)


async def test_create_thread_rejects_another_tenants_run_id(db_manager, db_session):
    """``sequence_runs.id`` is globally unique, so the FK alone would ACCEPT this.

    Only the tenant-scoped check refuses it. Without this, a run id learned from
    anywhere would let a caller link a thread across the isolation boundary (ADR-009).
    """
    mine, theirs = "tk_be9291_cmine", "tk_be9291_ctheirs"
    await _seed_run(db_session, theirs, _RUN)
    await _seed_run(db_session, mine, _OTHER_RUN)
    svc = _svc(db_manager, db_session)

    with pytest.raises(ValidationError):
        await svc.create_thread(subject="Chain: reaching over", sequence_run_id=_RUN, tenant_key=mine)


async def test_create_thread_refuses_a_second_hub_and_names_the_first(db_manager, db_session):
    """A restaged conductor must not be able to give a run a second hub.

    THE forward half of the double-link defect. The backfill guard closes the
    historical path; this closes the one a live conductor actually walks — step 0
    succeeds, the conductor dies before recording the thread id, it restages and runs
    step 0 again. Both hubs would carry the link, both would land in the FK branch of
    the resolver's CASE, and ``created_at`` ascending would answer every
    sub-orchestrator with the first, abandoned thread while the conductor polled the
    second. Nothing raises; the chain just goes quiet.

    The refusal NAMES the existing hub, because a restaged conductor's correct move is
    to adopt it. An error that only said "no" would strand the caller and move the
    failure rather than remove it.
    """
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
    """The other side of the guard: it refuses a collision, not a replacement.

    A soft-deleted hub is already invisible to resolution, so a conductor recreating
    one is doing the right thing. A guard that refused this would make a deleted
    thread permanently poison its own run.
    """
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
    """The new guard is tenant-scoped, so it can neither leak nor refuse across tenants.

    A cross-tenant run id is refused by the EXISTING check, and this pins that the new
    one adds no second, wider reason to say no.
    """
    mine, theirs = "tk_be9291_hmine", "tk_be9291_htheirs"
    await _seed_run(db_session, mine, _RUN)
    await _seed_run(db_session, theirs, _OTHER_RUN)
    svc = _svc(db_manager, db_session)
    await _seed_thread(db_session, theirs, "t_their_hub", 8801, "Chain: theirs", _JAN, run_id=_OTHER_RUN)

    created = await svc.create_thread(subject="Chain: mine", sequence_run_id=_RUN, tenant_key=mine)

    assert created["sequence_run_id"] == _RUN


async def test_a_plain_thread_is_unaffected(db_manager, db_session):
    """Nearly every thread is not a hub. Creating one without a run stays exactly as it was."""
    tenant = "tk_be9291_plain"
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)

    created = await _svc(db_manager, db_session).create_thread(subject="just a chat", tenant_key=tenant)

    assert created["sequence_run_id"] is None


async def test_purging_the_run_unlinks_the_hub_instead_of_deleting_it(db_manager, db_session):
    """``ON DELETE SET NULL`` is load-bearing, so it gets a test rather than a comment.

    A finished chain run is PURGED (SequenceRunService.purge_run) — that is the happy
    path, not an edge case. Under CASCADE this delete would take the hub thread and its
    entire coordination history with it every time a chain completed; under RESTRICT it
    would raise and break chain completion outright. The thread must survive, unlinked.
    """
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


# ---------------------------------------------------------------------------
# Composition pinned BY IDENTITY
# ---------------------------------------------------------------------------


def test_the_repository_serves_hub_resolution_by_identity():
    """Served BY the mixin, never shadowed on the repository — one source of truth.

    A redefinition on the concrete class would leave the mixin copy dead while still
    looking authoritative, which is the exact failure the five extractions before this
    one were pinned against.
    """
    assert CommThreadRepository.resolve_chain_hub_thread is RepoChainHubMixin.resolve_chain_hub_thread
    assert CommThreadRepository._require_sequence_run is RepoChainHubMixin._require_sequence_run


def test_the_service_serves_hub_resolution_by_identity():
    assert CommThreadService.resolve_chain_hub_thread is ServiceChainHubMixin.resolve_chain_hub_thread


def test_the_service_serves_the_conductor_resolver_by_identity():
    """The service serves the BUILDER MODULE's resolver — never a local shadow.

    Same one-source-of-truth property the two assertions above pin for the hub mixins.
    """
    assert mission_orchestration_service.resolve_conductor_early_return is resolve_conductor_early_return


async def test_the_conductor_branch_is_served_by_the_extracted_resolver(monkeypatch):
    """The project-less conductor branch is SERVED BY ``resolve_conductor_early_return``.

    BE-9291-F1 lifted that branch out of ``_build_orchestrator_context`` (296 lines
    against a 295 shrink-only budget — the guardrail-7 breach that reddened CI) and out
    of the module entirely, which sat at exactly its 835-line file budget. The hazard of
    any extraction is that someone later re-inlines the logic and leaves the extracted
    function dead while it still looks authoritative.

    Containment cannot catch that: a re-inlined duplicate contains the same code. Only
    SUBSTITUTION can. Swapping the resolver for a sentinel must change what the caller
    returns — so if the branch is ever inlined again, the sentinel is never consulted
    and this test goes red. Verified to bite: re-inlining the branch turns THIS test red
    while every conductor suite stays green.
    """
    svc = MissionOrchestrationService(db_manager=None, tenant_manager=TenantManager())  # type: ignore[arg-type]

    class _Job:
        job_type = "orchestrator"
        project_id = None  # the project-less conductor — this is the branch under test

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
