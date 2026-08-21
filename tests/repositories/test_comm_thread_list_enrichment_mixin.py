# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9289b — the Hub list's card facts, assembled in one round trip.

The Quiet Cards list shows three things per card: the thread's name, who registered on
it, and the last thing said — plus whether there is anything new. None of that was
fetchable from the thread list, so the UI issued a follow-up call per thread. This
replaces that N+1 with a single query over the page it already has.

Two properties are load-bearing and are pinned here rather than left to review:

- ``unread`` is a BOOLEAN produced by an ``EXISTS``, never a count that gets cast. The
  card's design bar is no numbers except relative times, and a count on the payload is
  an invitation to render one.
- The enrichment is ONE round trip. If it ever regresses into per-thread queries the
  N+1 is back and the whole point is lost.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, no module-level
mutable state, each test owns its setup, every query is tenant-scoped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories._comm_thread_list_enrichment_mixin import CommThreadListEnrichmentMixin
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_enrich_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_execution(
    db_session,
    tenant: str,
    agent_id: str,
    status: str,
    *,
    started_at: datetime | None,
    display_name: str = "Seeded Agent",
) -> None:
    """One ``agent_executions`` row for ``agent_id``. Several rows per agent is the
    normal case — succession reuses the agent_id — so these tests seed more than one."""
    with tenant_session_context(db_session, tenant):
        job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant,
            job_type="implementer",
        )
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant,
                agent_display_name=display_name,
                status=status,
                started_at=started_at,
            )
        )
        await db_session.flush()


async def _age_message(db_session, tenant: str, message_id: str, *, seconds: int = 60) -> None:
    """Push one post backwards in time so a "newest post" read has a real winner.

    Posts made inside one transaction share a ``created_at`` (``server_default=func.now()``
    and Postgres ``now()`` is the transaction timestamp), which production does not do —
    there each post commits on its own. Without this the ordering is a tie.
    """
    with tenant_session_context(db_session, tenant):
        await db_session.execute(
            update(Message)
            .where(Message.id == message_id, Message.tenant_key == tenant)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await db_session.flush()


async def _seed_project(db_session, tenant: str, name: str) -> str:
    with tenant_session_context(db_session, tenant):
        # BE-9437: a project belongs to a product. Its own, so an active
        # seed cannot collide under idx_project_single_active_per_product.
        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name=name,
            description="enrichment test project",
            mission="exercise the card facts",
            status="active",
            tenant_key=tenant,
            product_id=_owning_product_project.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()
    return project.id


# ---------------------------------------------------------------------------
# Composition — the house pattern for these extractions (three uses makes it canon).
# ---------------------------------------------------------------------------


def test_the_repository_serves_the_enrichment_by_identity():
    """Served BY the mixin, never shadowed on the repository — one source of truth. A
    redefinition would leave the mixin copy dead while still looking authoritative, and
    behavioural tests would keep passing right up until the two copies diverged."""
    assert issubclass(CommThreadRepository, CommThreadListEnrichmentMixin)
    assert CommThreadRepository.list_threads_enriched is CommThreadListEnrichmentMixin.list_threads_enriched


# ---------------------------------------------------------------------------
# The card facts.
# ---------------------------------------------------------------------------


async def test_card_facts_for_a_project_thread(db_manager, db_session):
    tenant = _tk("facts")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant, "Quiet Cards rollout")
    svc = _service(db_manager, db_session)

    thread = await svc.create_thread(subject="bound", creator_id="agent-orch", project_id=project_id, tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(
        thread_id=tid,
        participant_id="agent-alpha",
        display_name="Alpha",
        role="implementer",
        detected_harness="claude-code",
        tenant_key=tenant,
    )
    await svc.post_to_thread(thread_id=tid, content="shipping it now", from_agent="agent-alpha", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["project_name"] == "Quiet Cards rollout"
    assert card["last_message"]["excerpt"] == "shipping it now"
    assert card["last_message"]["author"] == "Alpha"
    assert card["last_message"]["created_at"]

    alpha = next(p for p in card["participants"] if p["participant_id"] == "agent-alpha")
    assert (alpha["display_name"], alpha["role"], alpha["harness"]) == ("Alpha", "implementer", "claude-code")
    assert "last_seen_at" in alpha


async def test_a_standalone_thread_has_no_project_name(db_manager, db_session):
    tenant = _tk("noproject")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="standalone", creator_id="agent-orch", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["project_name"] is None


async def test_a_silent_thread_has_no_last_message(db_manager, db_session):
    """A thread nobody has spoken in must not fabricate an excerpt."""
    tenant = _tk("silent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="quiet", creator_id="agent-orch", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["last_message"] is None
    assert card["unread"] is False  # nothing said means nothing to read


# ---------------------------------------------------------------------------
# unread — a boolean, per viewer, keyed on the stored read cursor.
# ---------------------------------------------------------------------------


async def test_unread_is_true_when_never_read(db_manager, db_session):
    """No participant row, or a NULL cursor, means nothing has been read — so any
    message at all counts. Honest "never read" semantics."""
    tenant = _tk("unread")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)
    await svc.post_to_thread(thread_id=thread["thread_id"], content="hi", from_agent="agent-a", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["unread"] is True


async def test_unread_is_a_boolean_not_a_count(db_manager, db_session):
    """Load-bearing: three unread messages must still read as True, not 3. A count on
    the payload is an invitation to render a number, and the card shows none."""
    tenant = _tk("bool")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    for n in range(3):
        await svc.post_to_thread(thread_id=tid, content=f"msg {n}", from_agent="agent-a", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["unread"] is True
    assert isinstance(card["unread"], bool)


async def test_unread_is_false_once_the_reader_has_drained_the_thread(db_manager, db_session):
    """Keys on comm_participants.last_read_at — the BE-9012a cursor, which the list
    never used before this."""
    tenant = _tk("read")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="reader-1", tenant_key=tenant)
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-a", tenant_key=tenant)
    await svc.get_thread_history(thread_id=tid, as_participant="reader-1", mark_read=True, tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="reader-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["unread"] is False


async def test_unread_is_per_viewer(db_manager, db_session):
    """Two people looking at the same list see different unread flags."""
    tenant = _tk("perviewer")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id="reader-1", tenant_key=tenant)
    await svc.post_to_thread(thread_id=tid, content="hi", from_agent="agent-a", tenant_key=tenant)
    await svc.get_thread_history(thread_id=tid, as_participant="reader-1", mark_read=True, tenant_key=tenant)

    drained = next(
        t for t in (await svc.list_threads(viewer_id="reader-1", tenant_key=tenant))["threads"] if t["thread_id"] == tid
    )
    fresh = next(
        t for t in (await svc.list_threads(viewer_id="reader-2", tenant_key=tenant))["threads"] if t["thread_id"] == tid
    )

    assert drained["unread"] is False
    assert fresh["unread"] is True


# ---------------------------------------------------------------------------
# FE-9418 — the message ANCHOR. Without an id the client can only guess the post.
# ---------------------------------------------------------------------------


async def test_last_message_names_the_post_it_describes(db_manager, db_session):
    """The card's last_message carries the id of the post it summarises.

    FE-9410 landed baton notifications inside the thread but could not point at the
    POST, because this payload named no message: the Hub had to approximate the target
    as "newest post at the moment you arrive", which is a different row from "the post
    that handed you the baton" as soon as anything else lands in between. This id is the
    anchor that removes the guess, and it is the only reachable source of one — the
    baton's own WS event (``broadcast_thread_update``) and its durable bell row
    (``HubBatonHandoverPayload``) both carry a thread id and no message id.

    Two posts are seeded deliberately: with one, an implementation that returned the
    OLDEST row, or any row, would still pass.

    The older post is explicitly aged, and that is required rather than tidy.
    ``Message.created_at`` is ``server_default=func.now()``, and Postgres ``now()`` is
    the TRANSACTION timestamp — so two posts made inside this suite's single
    rollback-bound transaction carry an IDENTICAL ``created_at`` and the LATERAL's
    ``ORDER BY created_at DESC LIMIT 1`` is a tie broken arbitrarily. Production does
    not have that tie (each post commits in its own transaction), so aging the row is
    what makes this test model production instead of the harness. There is no monotonic
    key on ``messages`` to tiebreak with, and the tie is harmless where it happens: one
    LATERAL row supplies the excerpt AND the anchor together, so the operator always
    lands on exactly the post the card described.
    """
    tenant = _tk("anchor")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="hand-off", creator_id="agent-orch", tenant_key=tenant))["thread_id"]

    older = await svc.post_to_thread(thread_id=tid, content="first", from_agent="agent-a", tenant_key=tenant)
    newest = await svc.post_to_thread(thread_id=tid, content="over to you", from_agent="agent-a", tenant_key=tenant)
    await _age_message(db_session, tenant, older["message_id"])

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["last_message"]["id"] == newest["message_id"]
    assert card["last_message"]["id"] != older["message_id"]
    assert card["last_message"]["excerpt"] == "over to you"


async def test_the_message_anchor_is_the_message_id_not_the_thread_id(db_manager, db_session):
    """The anchor must be Message.id, and this is the assertion that proves it.

    The outer select already carries ``CommThread.id``. Projecting the LATERAL's id
    WITHOUT a label puts two ``id`` columns in one row tuple, and attribute access
    resolves to the first — so the THREAD id would be served as the message anchor. The
    client would then deep-link to a message that does not exist, and every weaker
    assertion ("an id is present", "it is a string") would stay green. Only comparing it
    against the thread id catches that.
    """
    tenant = _tk("anchorlabel")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = (await svc.create_thread(subject="labelled", creator_id="agent-orch", tenant_key=tenant))["thread_id"]
    await svc.post_to_thread(thread_id=tid, content="a post", from_agent="agent-a", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == tid)

    assert card["last_message"]["id"] != tid
    assert card["last_message"]["id"] != card["thread_id"]


# ---------------------------------------------------------------------------
# Opt-in, and tenant isolation.
# ---------------------------------------------------------------------------


async def test_the_agent_path_stays_unenriched(db_manager, db_session):
    """No viewer means no card facts — the MCP list payload is unchanged, and unread is
    per-viewer so it cannot be answered without knowing who is asking."""
    tenant = _tk("optin")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    await svc.create_thread(subject="t", creator_id="agent-orch", tenant_key=tenant)

    listed = await svc.list_threads(tenant_key=tenant)

    assert listed["threads"]
    for key in ("project_name", "participants", "last_message", "unread"):
        assert key not in listed["threads"][0]


async def test_enrichment_is_tenant_scoped(db_manager, db_session):
    """Another tenant's participants and messages never bleed into these facts."""
    mine, theirs = _tk("mine"), _tk("theirs")
    await _seed(db_session, mine)
    await _seed(db_session, theirs)
    svc_mine = _service(db_manager, db_session)
    tid = (await svc_mine.create_thread(subject="t", creator_id="agent-orch", tenant_key=mine))["thread_id"]
    await svc_mine.post_to_thread(thread_id=tid, content="mine", from_agent="agent-a", tenant_key=mine)

    listed = await svc_mine.list_threads(viewer_id="operator-1", tenant_key=theirs)

    assert all(t["thread_id"] != tid for t in listed["threads"])


# ---------------------------------------------------------------------------
# Item 3 — honest titles, structurally and only structurally.
# ---------------------------------------------------------------------------


async def test_a_bound_thread_is_titled_from_its_project(db_manager, db_session):
    """A card must never read "(project comms)" — the machine-minted marker a
    system-created bound thread carries."""
    tenant = _tk("title")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant, "Message Hub redesign")
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(
        subject="(project comms)", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["title"] == "Message Hub redesign"
    # The STORED subject is untouched — it is load-bearing resolution machinery.
    assert card["subject"] == "(project comms)"


async def test_a_chain_hub_keeps_its_stored_subject_run_id_and_all(db_manager, db_session):
    """A chain hub's stored subject is handed back verbatim — titling must never parse,
    shorten or rewrite it.

    BE-9291 CORRECTED THIS DOCSTRING, not the assertions. It used to say the run_id in the
    subject "is the DISCOVERY KEY ... and there is no FK to fall back on". There is one now
    (``comm_threads.sequence_run_id``), so that reasoning is retired and a reader acting on
    it would be misled. The behaviour under test is unchanged and still correct: enrichment
    reports the stored subject as-is, whatever it happens to contain. Legacy hubs created
    before the FK still carry a run_id here and still resolve down the subject fallback, so
    rewriting the stored subject would still break them."""
    tenant = _tk("chainhub")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    run_id = str(uuid.uuid4())
    subject = f"Chain: Message Hub redesign - run {run_id}"
    thread = await svc.create_thread(subject=subject, creator_id="conductor", tenant_key=tenant)

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["title"] == subject
    assert run_id in card["title"]


async def test_a_bound_threads_organic_subject_still_yields_the_project_title(db_manager, db_session):
    """Structural means structural: bound threads take the project's name whatever
    their subject says, so the card and the 360 archive agree on what this is."""
    tenant = _tk("organic")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant, "Canonical Project Name")
    svc = _service(db_manager, db_session)
    thread = await svc.create_thread(
        subject="some agent's own wording", creator_id="agent-orch", project_id=project_id, tenant_key=tenant
    )

    listed = await svc.list_threads(viewer_id="operator-1", tenant_key=tenant)
    card = next(t for t in listed["threads"] if t["thread_id"] == thread["thread_id"])

    assert card["title"] == "Canonical Project Name"


# ---------------------------------------------------------------------------
# BE-9363 — the viewer's read cursor must correlate to the CURRENT thread.
# ---------------------------------------------------------------------------


async def test_thread_list_survives_a_viewer_who_belongs_to_several_threads(db_manager, db_session):
    """FAIL-FIRST: the whole list 500s once the viewer is a participant in more than
    one thread.

    ``last_read`` is consumed inside the ``unread`` EXISTS, whose own FROM is
    ``messages``. Without an explicit ``correlate(CommThread)`` SQLAlchemy cannot reach
    the outer ``comm_threads`` from that depth, so it adds one to the subquery's FROM
    and the correlation silently becomes a self-join across every thread. Postgres then
    raises CardinalityViolationError -- "more than one row returned by a subquery used
    as an expression" -- and GET /api/v1/threads returns 500 for that viewer.

    ``uq_comm_participant`` allows at most one participant row per (thread,
    participant), so more than one row can ONLY mean the correlation was lost.

    One thread is not enough to catch this: the bug needs the viewer joined to two.
    """
    tenant = _tk("multi")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    viewer = "operator-multi"

    first = await svc.create_thread(subject="first thread", creator_id="agent-orch", tenant_key=tenant)
    second = await svc.create_thread(subject="second thread", creator_id="agent-orch", tenant_key=tenant)
    for thread in (first, second):
        await svc.join_thread(thread_id=thread["thread_id"], participant_id=viewer, tenant_key=tenant)
    await svc.post_to_thread(
        thread_id=first["thread_id"], content="something new", from_agent="agent-orch", tenant_key=tenant
    )

    listed = await svc.list_threads(viewer_id=viewer, tenant_key=tenant)

    ids = {t["thread_id"] for t in listed["threads"]}
    assert {first["thread_id"], second["thread_id"]} <= ids

    # And the cursor still answers PER THREAD, not globally: only the thread that was
    # posted to is unread. A correlation that resolved against the wrong thread would
    # mark both, so this is what proves the fix rather than merely surviving the query.
    by_id = {t["thread_id"]: t for t in listed["threads"]}
    assert by_id[first["thread_id"]]["unread"] is True
    assert by_id[second["thread_id"]]["unread"] is False


# ---------------------------------------------------------------------------
# participants[].status — what drives the card's status dot (BE-9365b).
# ---------------------------------------------------------------------------


async def _card_with(svc, tenant: str, tid: str, viewer: str = "operator-1") -> dict:
    listed = await svc.list_threads(viewer_id=viewer, tenant_key=tenant)
    return next(t for t in listed["threads"] if t["thread_id"] == tid)


async def _join_and_card(svc, tenant: str, agent_id: str) -> dict:
    thread = await svc.create_thread(subject="status dot", creator_id="agent-orch", tenant_key=tenant)
    tid = thread["thread_id"]
    await svc.join_thread(thread_id=tid, participant_id=agent_id, display_name="Alpha", tenant_key=tenant)
    card = await _card_with(svc, tenant, tid)
    return next(p for p in card["participants"] if p["participant_id"] == agent_id)


async def test_participant_status_comes_from_the_latest_execution(db_manager, db_session):
    """The dot must show what the agent is doing NOW, not what it once did.

    Succession reuses one agent_id across several executions, so an agent that finished a
    job and was respawned has both a `complete` row and a `working` row. Reading the
    wrong one paints a live agent green-and-done, which is the exact class of lie the
    Quiet Cards honesty rule exists to prevent.
    """
    tenant = _tk("status_latest")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _seed_execution(db_session, tenant, "agent-alpha", "complete", started_at=datetime(2026, 1, 1, tzinfo=UTC))
    await _seed_execution(db_session, tenant, "agent-alpha", "working", started_at=datetime(2026, 6, 1, tzinfo=UTC))

    assert (await _join_and_card(svc, tenant, "agent-alpha"))["status"] == "working"


async def test_a_staged_successor_outranks_the_execution_it_replaced(db_manager, db_session):
    """A successor that has been staged but has not started yet has a NULL started_at.

    Postgres orders NULLs FIRST on DESC, so it wins — which is what we want: the agent's
    current state is "staged", not the predecessor's "complete". If this ever flips to
    NULLS LAST the card would show a finished agent for a thread that just got a fresh
    one, so the ordering is asserted rather than assumed.
    """
    tenant = _tk("status_staged")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    await _seed_execution(db_session, tenant, "agent-beta", "complete", started_at=datetime(2026, 5, 1, tzinfo=UTC))
    await _seed_execution(db_session, tenant, "agent-beta", "staged", started_at=None)

    assert (await _join_and_card(svc, tenant, "agent-beta"))["status"] == "staged"


async def test_status_is_null_when_the_agent_never_registered_an_execution(db_manager, db_session):
    """No execution row => NULL, deliberately NOT coalesced to a default.

    The client renders NULL as a hollow ring ("never checked in") and a missing status as
    slate. Defaulting here — to `idle`, or worse to anything green — would make an agent
    that never arrived indistinguishable from one that is healthy and watching. Absent
    data must not read as healthy.
    """
    tenant = _tk("status_absent")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)

    participant = await _join_and_card(svc, tenant, "agent-ghost")
    assert "status" in participant, "the key must be present so the client can distinguish it from an old payload"
    assert participant["status"] is None


async def test_participant_status_is_tenant_scoped(db_manager, db_session):
    """An agent_id is only unique within a tenant, so the join MUST carry tenant_key.

    Without it another tenant's execution for a same-named agent would supply the status
    — a cross-tenant read on the isolation boundary, not merely a wrong colour.
    """
    mine = _tk("status_mine")
    theirs = _tk("status_theirs")
    await _seed(db_session, mine)
    await _seed(db_session, theirs)
    svc = _service(db_manager, db_session)

    # Same agent_id, different tenant, and the only execution row in existence.
    await _seed_execution(db_session, theirs, "agent-shared", "working", started_at=datetime(2026, 6, 1, tzinfo=UTC))

    assert (await _join_and_card(svc, mine, "agent-shared"))["status"] is None
