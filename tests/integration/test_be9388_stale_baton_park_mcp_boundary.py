# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9388 — ``get_my_turn`` must be able to PARK, across the MCP transport.

BE-9296a shipped a wake primitive whose blocking path was unreachable. On its
first live park it returned ``already_pending`` with ``waited_seconds=0``, every
call, forever, for every agent in the tenant — turning the documented
``while: get_my_turn()`` loop into a zero-delay spin that reports an
urgent-looking ``woken=true`` each iteration. Three threads left at baton ``all``
(two ``resolved``, one ``open``, the oldest three weeks old, none belonging to the
parking agent) were enough to disable the primitive tenant-wide.

The shipping probe measured wake LATENCY on fresh threads with fresh agent ids,
so it never exercised the idle path against accumulated data and the defect was
invisible. These tests exercise the idle path: they assert the primitive can
reach ``timeout``, which is the one outcome the broken build could never produce.

Three fixes, three layers, and a test for each — because the obvious one is not
sufficient on its own:

* (A) terminal threads are excluded from BOTH baton arms. A resolved thread holds
  nobody's turn. Kills two of the three observed offenders.
* (B) the ``all`` arm requires PARTICIPATION. ``all`` means "all participants",
  which is what the write side already means by it (``_wake_targets`` fans an
  ``all`` baton out to ``participant_ids`` only) and what the baton refusal hint
  already tells callers. Kills the third observed offender.
* (C) an ``all`` baton does not pre-empt the PARK. It is a standing state, not a
  new event — the same reasoning that already excludes ``loop_directives`` from
  ``_has_pending_work``. Without it the class survives (A)+(B): pass the baton to
  ``all`` on a live healthy thread and every participant's park is disabled until
  someone explicitly moves it off ``all``, and nothing clears ``all`` implicitly.

The other half of the file is the anti-regression half, and it is not optional:
the spin must not be cured by breaking delivery. A named baton, a directed
action, and a real ``all`` hand-off to an agent that is genuinely parked must all
still arrive instantly.

Boundary-level because the failing surface is the ``@mcp.tool`` wrapper an agent
actually calls (house law: regression test at the layer the bug lived).

Parallel-safe: fresh tenant_key per test via the shared fixture, rolled-back
db_session, no module-level mutable state, no ordering dependencies.
"""

from __future__ import annotations

import asyncio
import json

from giljo_mcp.services.agent_wake_registry import get_wake_registry
from giljo_mcp.services.comm_thread_service import CommThreadService

# The BE-9296a fixture is exactly the harness this needs — the real service bound
# to the rolled-back session, so a write in the test is visible to the tool call.
# Imported rather than duplicated (precedent: test_be9253_listing_profile.py).
from tests.integration.test_be9296a_await_my_turn_mcp_boundary import wake_mcp_client  # noqa: F401


# A park that is working returns at its timeout, not before. Kept short so the
# suite pays a second per parking test rather than the 60s default.
PARK_SECONDS = 1
# A delivery that is working arrives in well under this. Generous enough not to
# flake on a loaded box, tight enough that a full park (PARK_SECONDS) cannot be
# mistaken for an instant return.
WAKE_DEADLINE_SECONDS = 2.0


def _payload(result) -> dict:
    """The tool's JSON body as a dict."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


async def _thread(service: CommThreadService, tenant_key: str, *, joiners: tuple[str, ...] = ()) -> str:
    """A thread created by 'em', with ``joiners`` registered as participants."""
    created = await service.create_thread(subject="be9388", creator_id="em", tenant_key=tenant_key)
    thread_id = created["thread_id"]
    for agent in joiners:
        await service.join_thread(thread_id=thread_id, participant_id=agent, tenant_key=tenant_key)
    return thread_id


async def _await_turn(client_factory, agent_id: str, *, timeout: int = PARK_SECONDS) -> dict:
    async with client_factory() as client:
        result = await client.call_tool("get_my_turn", {"agent_id": agent_id, "wait_seconds": timeout})
    assert result.is_error is False
    return _payload(result)


# ---------------------------------------------------------------------------
# The park must be reachable — one test per fix, each red before its own fix
# ---------------------------------------------------------------------------


async def test_a_resolved_thread_holding_the_all_baton_does_not_block_the_park(wake_mcp_client):  # noqa: F811
    """(A) The observed offender: CHT-0472 / CHT-0425 in miniature.

    A thread the agent PARTICIPATES in, left at baton 'all' and then resolved.
    Before the fix this returned already_pending forever — the whole defect, in
    four lines of setup.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)
    await service.post_to_thread(
        thread_id=thread_id, content="done", from_agent="em", set_status="resolved", tenant_key=tenant_key
    )

    body = await _await_turn(client_factory, "worker-1")

    assert body["wake_reason"] == "timeout", "a resolved thread must not hold anybody's turn"
    assert body["woken"] is False
    assert thread_id not in [t["thread_id"] for t in body["threads"]]


async def test_a_resolved_thread_holding_a_named_baton_does_not_block_the_park(wake_mcp_client):  # noqa: F811
    """(A) on the other baton arm — the named one, not just 'all'.

    Both arms queried without a status filter; fixing only the arm the incident
    happened to travel would leave the same defect one hand-off away.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant_key)
    await service.post_to_thread(
        thread_id=thread_id, content="done", from_agent="em", set_status="closed", tenant_key=tenant_key
    )

    body = await _await_turn(client_factory, "worker-1")

    assert body["wake_reason"] == "timeout"
    assert thread_id not in [t["thread_id"] for t in body["threads"]]


async def test_b_an_all_baton_does_not_reach_an_agent_who_never_joined(wake_mcp_client):  # noqa: F811
    """(B) The sufficiency gap: CHT-0427 was OPEN, so (A) alone never touched it.

    'all' means all PARTICIPANTS. A stranger polling this tenant must not inherit
    a turn on a conversation it was never part of — which is exactly how three
    abandoned threads disabled the primitive for every agent in the tenant.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)

    body = await _await_turn(client_factory, "stranger-1")

    assert body["wake_reason"] == "timeout", "'all' must mean all participants, not every agent in the tenant"
    assert body["count"] == 0
    assert body["threads"] == []


async def test_c_a_standing_all_baton_does_not_pre_empt_a_participants_park(wake_mcp_client):  # noqa: F811
    """(C) The failure that needs no stale data at all.

    A live, healthy, OPEN thread; the agent is a legitimate participant; the baton
    was handed to 'all' by ordinary documented usage. (A) and (B) both pass it
    through, and the participant can never park again until someone explicitly
    moves the baton off 'all' — which nothing does implicitly.

    A standing 'all' baton is a STATE, not an event. Same reasoning that already
    excludes loop_directives from _has_pending_work; the identical failure simply
    walked in through the baton axis.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)

    body = await _await_turn(client_factory, "worker-1")

    assert body["wake_reason"] == "timeout", "a standing 'all' baton must not disable the park"
    assert body["woken"] is False
    # Nothing is HIDDEN by (C) — the poll surface still reports the thread, so an
    # agent reading the timeout payload still learns the invitation exists. Only
    # the park gate stops treating it as a new event.
    assert thread_id in [t["thread_id"] for t in body["threads"]]


# ---------------------------------------------------------------------------
# Delivery must survive the fix — curing the spin by going deaf would be worse
# ---------------------------------------------------------------------------


async def test_a_named_baton_still_wakes_instantly(wake_mcp_client):  # noqa: F811
    """The baton pointed AT me is real work and must still pre-empt the park."""
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))
    await service.pass_baton(thread_id=thread_id, to="worker-1", tenant_key=tenant_key)

    body = await asyncio.wait_for(_await_turn(client_factory, "worker-1", timeout=30), WAKE_DEADLINE_SECONDS)

    assert body["wake_reason"] == "already_pending"
    assert body["woken"] is True
    assert body["waited_seconds"] == 0
    assert thread_id in [t["thread_id"] for t in body["threads"]]


async def test_a_directed_action_still_wakes_instantly(wake_mcp_client):  # noqa: F811
    """The BE-9207 axis is untouched: an unresolved directive addressed to me
    still counts as pending work even though the baton may sit elsewhere."""
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1", "worker-2"))
    # Baton goes to someone ELSE; the directive is mine. Only the directed arm
    # can surface this, which is what makes it the right pin.
    await service.post_to_thread(
        thread_id=thread_id,
        content="please review",
        from_agent="em",
        to_participant="worker-1",
        requires_action=True,
        tenant_key=tenant_key,
    )
    await service.pass_baton(thread_id=thread_id, to="worker-2", tenant_key=tenant_key)

    body = await asyncio.wait_for(_await_turn(client_factory, "worker-1", timeout=30), WAKE_DEADLINE_SECONDS)

    assert body["wake_reason"] == "already_pending"
    assert [d["thread_id"] for d in body["directed_action"]] == [thread_id]


async def test_a_real_all_handoff_still_wakes_a_parked_participant_instantly(wake_mcp_client):  # noqa: F811
    """THE test that makes (C) safe rather than merely quiet.

    (C) stops a standing 'all' baton from pre-empting the park. It must NOT stop a
    FRESH 'all' hand-off from reaching an agent that is already parked — that path
    runs through the wake registry, which set_next_actor signals to every participant,
    independent of _has_pending_work. Park first, then hand off, and the wake must
    still arrive in under a second.

    Waiting on the waiter's own read to FINISH (not merely on its registration) is
    load-bearing: this fixture shares one rollback-isolated session between the
    in-flight tool call and the write below, and two coroutines using one session
    interleave the tenant guard's context. A harness artifact — every real request
    owns its session — but it would surface as a confusing isolation error rather
    than a wake bug.
    """
    client_factory, tenant_key, service = wake_mcp_client
    thread_id = await _thread(service, tenant_key, joiners=("worker-1",))

    async with client_factory() as client:
        read_done = asyncio.Event()
        original_get_my_turn = service.get_my_turn

        async def _instrumented(**kwargs):
            result = await original_get_my_turn(**kwargs)
            read_done.set()
            return result

        service.get_my_turn = _instrumented  # type: ignore[method-assign]
        call = asyncio.create_task(client.call_tool("get_my_turn", {"agent_id": "worker-1", "wait_seconds": 10}))
        await asyncio.wait_for(read_done.wait(), timeout=WAKE_DEADLINE_SECONDS)
        assert get_wake_registry().waiter_count(tenant_key) >= 1, "waiter read but never parked"

        await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)
        result = await asyncio.wait_for(call, timeout=WAKE_DEADLINE_SECONDS)

    body = _payload(result)
    assert body["woken"] is True
    assert body["wake_reason"] == "signalled", "a fresh 'all' hand-off must still reach a parked participant"
    assert thread_id in [t["thread_id"] for t in body["threads"]]


async def test_the_three_observed_threads_replayed_together(wake_mcp_client):  # noqa: F811
    """The live incident, reconstructed: all three offenders at once.

    The observed payload was ``count=3`` with ``already_pending`` and
    ``waited_seconds=0`` for a fresh agent id that owned no work anywhere:

      CHT-0472  resolved  next_action_owner='all'   (killed by A)
      CHT-0427  open      next_action_owner='all'   (killed by B — A never touched it)
      CHT-0425  resolved  next_action_owner='all'   (killed by A)

    Each axis has its own focused test above; this one exists because the axes
    were only ever observed TOGETHER, and a fix that cleared two of three would
    have left the primitive just as unusable while looking two-thirds correct.
    The assertion is the live symptom inverted: count 3 -> 0, already_pending ->
    timeout.

    The 'open' thread carries participants that are not the polling agent, as the
    real one does — its 13 registered lanes were all retired ids from a sprint
    three weeks earlier, which is precisely why no live agent could ever clear it.
    """
    client_factory, tenant_key, service = wake_mcp_client

    resolved_a = await _thread(service, tenant_key, joiners=("worker-1",))
    still_open = await _thread(service, tenant_key, joiners=("retired-lane-1", "retired-lane-2"))
    resolved_b = await _thread(service, tenant_key, joiners=("worker-1",))

    for thread_id in (resolved_a, still_open, resolved_b):
        await service.pass_baton(thread_id=thread_id, to="all", tenant_key=tenant_key)
    for thread_id in (resolved_a, resolved_b):
        await service.post_to_thread(
            thread_id=thread_id, content="wrapping up", from_agent="em", set_status="resolved", tenant_key=tenant_key
        )

    body = await _await_turn(client_factory, "fresh-agent-with-no-work")

    assert body["wake_reason"] == "timeout"
    assert body["woken"] is False
    assert body["count"] == 0, "three abandoned 'all' batons must not hold a fresh agent's turn"


async def test_the_idle_payload_is_empty_rather_than_urgent_looking(wake_mcp_client):  # noqa: F811
    """The symptom an operator actually saw: 'woken=true' with nothing to act on.

    An agent with genuinely no work must get an honest empty timeout, because the
    documented park loop branches on `woken` — a permanent `true` is what turned
    the loop into a spin.
    """
    client_factory, tenant_key, service = wake_mcp_client
    await _thread(service, tenant_key, joiners=("worker-1",))

    body = await _await_turn(client_factory, "worker-1")

    assert body["woken"] is False
    assert body["wake_reason"] == "timeout"
    assert body["count"] == 0
    assert body["directed_action"] == []
