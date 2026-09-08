# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary tests for BE-9292a — the participant registry is the
authority for who can acknowledge a post and who can be handed the baton.

Two mechanism gaps, both of the class where a careful agent does everything right
and still fails, so prose cannot fix either one:

GAP 1 — delivery without enrolment. A directed post wrote a ``message_recipients``
row for its target and no ``comm_participants`` row, so the addressee was counted
as owing a reply, was blocked at closeout for not draining it, and was
STRUCTURALLY unable to drain it: ``mark_read`` gates on enrolment, not delivery.
Observed 2026-07-25 — a sub-orchestrator wedged on its own closeout until it
guessed at ``join_thread``. Enrolment now happens where delivery does.

GAP 2 — an unvalidated baton hand-off. ``pass_baton_to`` was written straight
through with no check that it named a reachable participant, and the post still
answered ``baton_passed: true``. A mistyped or display-label target stranded the
chain with no error, no log line, and a success response — the conductor simply
never woke. The target is now validated against the thread's registry and an
undeliverable one is refused with the ids that WOULD work.

Behaviors under test (over the wire, the layer the bug lives at per CLAUDE.md):
- an agent that never posted, holding an unacked directed requires_action post,
  drains successfully with mark_read (the gap-1 reproduction);
- a reader with NOTHING delivered to it is still refused (the safety property
  gap 1 must not trade away);
- an undeliverable ``pass_baton_to`` is a structured rejection that moves no
  baton and persists no message;
- the directed auto-pass to a first-contact recipient still works (that post
  enrols its own target, so the hand-off is deliverable by the time it lands);
- reserved 'all' / 'none' are untouched;
- ``set_next_actor`` refuses the same undeliverable target.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.comm_baton_targets import TARGET_IS_A_DISPLAY_NAME
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def comm_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key, db_session)`` for FastMCP transport tests.

    Mirrors the BE-9012a boundary fixture: CommThreadService receives
    ``test_session`` from ToolAccessor, so its writes land in the rolled-back
    transaction (visible to db_session queries, never committed).
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    user = User(id=str(uuid4()), tenant_key=tenant_key, username=f"patrik_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _call(new_client, tool: str, args: dict):
    async with new_client() as s:
        return await s.call_tool(tool, args)


async def _thread_with_em(new_client) -> str:
    """A thread whose creator 'em' holds the baton. Nobody else is enrolled."""
    res = await _call(new_client, "create_thread", {"subject": "registry", "creator_id": "em"})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread_id"]


async def _baton_owner(new_client, thread_id: str) -> str | None:
    res = await _call(new_client, "get_thread_history", {"thread_id": thread_id})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread"]["next_action_owner"]


# ---------------------------------------------------------------------------
# GAP 1 — delivery implies enrolment
# ---------------------------------------------------------------------------


async def test_directed_action_recipient_can_drain_without_ever_posting(comm_mcp_client):
    """THE gap-1 reproduction (fails before the fix with NOT_A_PARTICIPANT).

    'lane-x' never joined and never posted. It is handed a directed
    requires_action post — so it is a recipient, it is counted as owing a reply,
    and closeout blocks on it. It must therefore be able to acknowledge it.
    """
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    posted = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "lane-x: your gate needs a decision",
            "from_agent": "em",
            "to_participant": "lane-x",
            "requires_action": True,
        },
    )
    assert posted.is_error is False, _error_text(posted)
    assert _payload(posted)["recipients"] == ["lane-x"]

    drained = await _call(
        new_client,
        "get_thread_history",
        {"thread_id": tid, "as_participant": "lane-x", "unread_only": True, "mark_read": True},
    )
    assert drained.is_error is False, _error_text(drained)
    body = _payload(drained)
    assert body.get("success") is not False, f"reader was refused its own directed post: {body}"
    assert body["marked_read"] >= 1
    assert any("your gate needs a decision" in m["content"] for m in body["messages"])


async def test_directed_recipient_is_enrolled_in_the_directory(comm_mcp_client):
    """The registries cannot diverge any more: a delivered post means a row in the
    participant directory, so the Hub's directory and the closeout gate agree."""
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    posted = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "for you only", "from_agent": "em", "to_participant": "lane-y"},
    )
    assert posted.is_error is False, _error_text(posted)

    with tenant_session_context(db_session, tenant_key):
        row = (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant_key,
                    CommParticipant.thread_id == tid,
                    CommParticipant.participant_id == "lane-y",
                )
            )
        ).scalar_one_or_none()
    assert row is not None, "a directed post must enrol its addressee"
    assert row.participant_type == "agent"


async def test_reader_with_nothing_delivered_is_still_refused(comm_mcp_client):
    """The safety property gap 1 must NOT trade away. Enrolment follows DELIVERY,
    not asking: a stranger with no post addressed to it still gets the structured
    NOT_A_PARTICIPANT rejection, so mark_read never silently acks a thread the
    caller has no standing on."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)
    posted = await _call(new_client, "post_to_thread", {"thread_id": tid, "content": "town square", "from_agent": "em"})
    assert posted.is_error is False, _error_text(posted)

    res = await _call(
        new_client, "get_thread_history", {"thread_id": tid, "as_participant": "ghost", "mark_read": True}
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False
    assert body["error"] == "NOT_A_PARTICIPANT"


# ---------------------------------------------------------------------------
# GAP 2 — the baton target must be reachable
# ---------------------------------------------------------------------------


async def test_undeliverable_baton_target_is_rejected_not_silently_accepted(comm_mcp_client):
    """THE gap-2 reproduction (before the fix this answered baton_passed: true).

    The live shape: a conductor posts under the display LABEL 'Ledger Zero
    Conductor' while polling get_my_turn under its registered id, so a hand-off
    to the label is unroutable. The refusal names the ids that would work.
    """
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)
    joined = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": "lane-a"})
    assert joined.is_error is False, _error_text(joined)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "DONE - baton back to you",
            "from_agent": "lane-a",
            "pass_baton_to": "Ledger Zero Conductor",
        },
    )
    assert res.is_error is False, _error_text(res)  # BE-6081 domain rejection, not an error
    body = _payload(res)
    assert body["success"] is False
    assert body["error"] == "BATON_TARGET_NOT_A_PARTICIPANT"
    assert body["requested"] == "Ledger Zero Conductor"
    assert "em" in body["valid_participants"]
    assert "lane-a" in body["valid_participants"]

    # The baton did not move, and the post did not land: a refused hand-off is
    # refused whole (validation runs before any write).
    assert await _baton_owner(new_client, tid) == "em"
    with tenant_session_context(db_session, tenant_key):
        count = (await db_session.execute(select(func.count(Message.id)).where(Message.thread_id == tid))).scalar_one()
    assert count == 0, "a rejected post must persist no message"


async def test_pass_baton_tool_refuses_the_same_undeliverable_target(comm_mcp_client):
    """The standalone hand-off has the identical failure mode and the identical
    guard — otherwise the fix is one call away from being bypassed."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(new_client, "set_next_actor", {"thread_id": tid, "to": "ghost-conductor"})
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False
    assert body["error"] == "BATON_TARGET_NOT_A_PARTICIPANT"
    assert body["valid_participants"] == ["em"]
    # Reports the owner it did NOT change — a consumer patching next_action_owner from
    # this response lands on the truth rather than blanking a baton that never moved.
    assert body["next_action_owner"] == "em"
    assert await _baton_owner(new_client, tid) == "em"


async def test_reserved_baton_targets_and_registered_participants_still_work(comm_mcp_client):
    """Museum guard: 'all', 'none' and a genuinely registered participant behave
    exactly as before — the validation only refuses what could never be delivered."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)
    joined = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": "lane-a"})
    assert joined.is_error is False, _error_text(joined)

    to_participant = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "over to you", "from_agent": "em", "pass_baton_to": "lane-a"},
    )
    assert to_participant.is_error is False, _error_text(to_participant)
    assert _payload(to_participant)["baton_passed"] is True
    assert await _baton_owner(new_client, tid) == "lane-a"

    to_all = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "ACCEPTED", "from_agent": "lane-a", "pass_baton_to": "all"},
    )
    assert to_all.is_error is False, _error_text(to_all)
    assert await _baton_owner(new_client, tid) == "all"

    to_none = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "fyi", "from_agent": "lane-a", "pass_baton_to": "none"},
    )
    assert to_none.is_error is False, _error_text(to_none)
    assert _payload(to_none)["baton_passed"] is False
    assert await _baton_owner(new_client, tid) == "all"


async def test_directed_auto_pass_to_first_contact_recipient_still_works(comm_mcp_client):
    """The BE-9197 auto-pass hands the baton to a to_participant that may never
    have joined. That post ENROLS its own addressee, so the hand-off is
    deliverable by the time it lands and must not be refused."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "lane-z: take it",
            "from_agent": "em",
            "to_participant": "lane-z",
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body.get("success") is not False, f"first-contact directed hand-off was refused: {body}"
    assert body["baton_passed"] is True
    assert await _baton_owner(new_client, tid) == "lane-z"

    turn = await _call(new_client, "get_my_turn", {"agent_id": "lane-z"})
    assert turn.is_error is False, _error_text(turn)
    assert tid in {t["thread_id"] for t in _payload(turn)["threads"]}


async def test_first_post_by_an_unjoined_author_can_still_hand_off_to_itself(comm_mcp_client):
    """An author's very first post enrols the author, so naming itself as the
    baton target is deliverable — the validation must consider the identities
    THIS post registers, not only the ones already on file."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "picking this up", "from_agent": "lane-new", "pass_baton_to": "lane-new"},
    )
    assert res.is_error is False, _error_text(res)
    assert _payload(res).get("success") is not False
    assert await _baton_owner(new_client, tid) == "lane-new"


# ---------------------------------------------------------------------------
# GAP 2 (continued) — the AUTO-PASS path, where the guard first shipped blind
# ---------------------------------------------------------------------------

_CONDUCTOR_UUID = "36eac157-bf1e-466e-9e51-91485f46ee62"
_CONDUCTOR_LABEL = "Ledger Zero Conductor"


async def _thread_with_labelled_conductor(new_client) -> str:
    """A thread where the conductor is registered under a UUID and renders under a
    friendly display name — the identity split that made the incident possible."""
    tid = await _thread_with_em(new_client)
    joined = await _call(
        new_client,
        "join_thread",
        {"thread_id": tid, "agent_id": _CONDUCTOR_UUID, "display_name": _CONDUCTOR_LABEL},
    )
    assert joined.is_error is False, _error_text(joined)
    return tid


async def test_auto_pass_to_a_display_label_cannot_strand_the_conductor(comm_mcp_client):
    """THE incident, reproduced through the DEFAULT hand-off path, with no prior state.

    The first pass of this project validated ``pass_baton_to`` but exempted
    ``to_participant`` as an identity the post itself enrols — which is correct for a
    genuine first-contact addressee and WRONG here, because the BE-9197 auto-pass sets
    ``pass_baton_to := to_participant``. The exemption therefore excused the auto-pass
    from the very check it was written for, and the guard could not fire on the
    commonest hand-off there is.

    A sub-orchestrator reads the thread, sees ``from_display_name`` and addresses its
    DONE to that label. Pre-fix: the auto-pass fired, validation exempted it, the baton
    was set to a string nobody polls under, a phantom participant was minted for the
    label, and the response said ``baton_passed: true``. The chain went quiet.
    """
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "DONE - lane complete, baton back to you",
            "from_agent": "sub-orch",
            "to_participant": _CONDUCTOR_LABEL,
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)

    # The property that matters, stated as the outcome rather than the mechanism:
    # the conductor polls under its registered id, so the baton must never come to
    # rest on a string that id would not match.
    owner = await _baton_owner(new_client, tid)
    assert owner != _CONDUCTOR_LABEL, "the baton was handed to a display label — the conductor is stranded"
    turn = await _call(new_client, "get_my_turn", {"agent_id": _CONDUCTOR_UUID})
    assert turn.is_error is False, _error_text(turn)
    reachable = tid in {t["thread_id"] for t in _payload(turn)["threads"]}
    assert reachable or owner == "em", "baton neither reachable by the conductor nor left where it was"

    # And the refusal names the id that would have worked, so the caller can retry.
    assert body["success"] is False
    assert body["error"] == TARGET_IS_A_DISPLAY_NAME
    assert body["registered_id"] == _CONDUCTOR_UUID
    assert _CONDUCTOR_UUID in body["hint"]


async def test_a_directed_post_to_a_label_mints_no_phantom_participant(comm_mcp_client):
    """The second-order half: a refused hand-off must also leave the directory clean.

    ``enrol_addressee`` registers whoever a post is delivered to, so an addressee that
    is really a display label used to be minted as a participant row. That row then
    joined ``valid_participants`` — the very allowlist the baton validator trusts — so
    the guard degraded a little with every mistyped addressee.
    """
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "status for you",
            "from_agent": "sub-orch",
            "to_participant": _CONDUCTOR_LABEL,
            "requires_action": True,
        },
    )

    with tenant_session_context(db_session, tenant_key):
        phantom = (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant_key,
                    CommParticipant.thread_id == tid,
                    CommParticipant.participant_id == _CONDUCTOR_LABEL,
                )
            )
        ).scalar_one_or_none()
    assert phantom is None, "a display label was minted as a participant beside the id it shadows"


async def test_a_minted_label_cannot_launder_a_later_explicit_hand_off(comm_mcp_client):
    """The permanence claim, pinned end to end.

    If a phantom row for the label ever reaches the directory, a LATER explicit
    ``pass_baton_to`` naming that label passes the registry check on the phantom's own
    row and strands the chain again — this time with the validator's blessing. The
    collision check therefore has to outrank registration: a string that is a display
    name held by a DIFFERENT registered id is refused whether or not something already
    minted it.
    """
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    # Try to seed the phantom exactly as the incident did.
    await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "first contact",
            "from_agent": "sub-orch",
            "to_participant": _CONDUCTOR_LABEL,
            "requires_action": True,
        },
    )

    # Now the explicit hand-off, the path the first pass of this project did guard.
    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "explicitly yours",
            "from_agent": "sub-orch",
            "pass_baton_to": _CONDUCTOR_LABEL,
        },
    )
    assert res.is_error is False, _error_text(res)
    body = _payload(res)
    assert body["success"] is False, "a minted label laundered a later explicit hand-off past the validator"
    assert body["error"] == TARGET_IS_A_DISPLAY_NAME
    assert await _baton_owner(new_client, tid) != _CONDUCTOR_LABEL


async def test_a_label_that_shadows_nobody_is_still_a_legitimate_addressee(comm_mcp_client):
    """The regression the narrow fix must NOT cause. Refusing unregistered addressees
    wholesale would break first-contact directed posts — a legitimate, common and
    previously working pattern. Only a genuine collision is refused."""
    new_client, _tk, _sess = comm_mcp_client
    tid = await _thread_with_labelled_conductor(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "lane-z: take it",
            "from_agent": "em",
            "to_participant": "lane-z-never-seen",
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    assert _payload(res).get("success") is not False, "a plain first-contact addressee was refused"
    assert await _baton_owner(new_client, tid) == "lane-z-never-seen"


# ---------------------------------------------------------------------------
# BE-9365b — the "user" alias, over the wire.
#
# This lives at the boundary and not only in the service because the alias exists
# SOLELY for agents, and agents only ever reach it through the MCP tool surface. A
# service-layer test would prove the resolver works while leaving the thing an agent
# actually types untested — the precise gap that let a broken tool wrapper ship green
# in BE-5042.
# ---------------------------------------------------------------------------


async def _the_operator(db_session, tenant_key: str) -> str:
    """The tenant's single human. tenant_key is per-USER and 1:1 (ADR-009)."""
    rows = await db_session.execute(select(User.id).where(User.tenant_key == tenant_key))
    ids = list(rows.scalars().all())
    assert len(ids) == 1, "fixture invariant: one operator per tenant"
    return ids[0]


async def test_an_agent_can_hand_the_baton_to_the_operator_by_the_name_user(comm_mcp_client):
    """The whole point: an agent knows the word "user", never the operator's uuid.

    Before this, an agent needing a human decision had one move it knew about —
    broadcast "waiting for you" into the room — leaving next_action_owner pointing at
    nobody. The Hub card's honesty rule paints yellow ONLY from the baton and never from
    the words in a post, so those requests were invisible by design. This is what gives
    the rule something true to fire on.
    """
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "Need your call on the pricing copy before I ship.",
            "from_agent": "em",
            "to_participant": "user",
            "requires_action": True,
        },
    )
    assert res.is_error is False, _error_text(res)
    assert _payload(res).get("success") is not False, "the operator alias was refused"

    # Resolved to the real id — NOT left as the literal "user", which no get_my_turn
    # could ever match. That silent-dead-baton shape is exactly what BE-9292a fixed.
    operator_id = await _the_operator(db_session, tenant_key)
    assert await _baton_owner(new_client, tid) == operator_id


async def test_pass_baton_accepts_the_operator_alias_too(comm_mcp_client):
    """Both entry points, or the alias is a trap: an agent that learns it from
    post_to_thread would reasonably try it on set_next_actor and strand the turn."""
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(new_client, "set_next_actor", {"thread_id": tid, "to": "user"})
    assert res.is_error is False, _error_text(res)

    operator_id = await _the_operator(db_session, tenant_key)
    assert await _baton_owner(new_client, tid) == operator_id


async def test_the_operator_alias_enrols_the_operator_as_a_user_not_an_agent(comm_mcp_client):
    """Delivery is enrolment, and the KIND is recorded once and never revised.

    An operator stamped 'agent' would render as an agent in the Hub directory
    permanently — a mis-attribution that outlives the post that caused it.
    """
    new_client, tenant_key, db_session = comm_mcp_client
    tid = await _thread_with_em(new_client)

    res = await _call(
        new_client,
        "post_to_thread",
        {"thread_id": tid, "content": "your call", "from_agent": "em", "to_participant": "user"},
    )
    assert res.is_error is False, _error_text(res)

    operator_id = await _the_operator(db_session, tenant_key)
    rows = await db_session.execute(
        select(CommParticipant.participant_type).where(
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.thread_id == tid,
            CommParticipant.participant_id == operator_id,
        )
    )
    assert rows.scalar_one() == "user"
