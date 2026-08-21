# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9388 — the baton query's two predicates + the park gate's one rule.

Complements the MCP-boundary regression with owning-layer coverage: what
``get_my_turn`` may report (service + repo), and what counts as pending work for
the PARK specifically (``_has_pending_work``, a pure function). Both halves
matter because the fix deliberately splits across them — the query change makes
the poll surface honest, the gate change is what makes the park reachable, and
neither alone is sufficient.

The pinned NEGATIVES are the load-bearing ones here: the fix must not over-narrow
into a delivery regression, so a named baton without participation, and a
directed action on a thread owned by somebody else, are both asserted to keep
working.

Real DB (rollback-isolated db_session), parallel-safe (no module globals).

Edition Scope: Both (Hub core).
"""

from __future__ import annotations

import pytest

from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _comm(db_session) -> CommThreadService:
    return CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)


async def _seed_cht(db_session, tenant_key: str) -> None:
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)


async def _thread(comm, tenant, *, joiners=()):
    created = await comm.create_thread(subject="baton", creator_id="EM", tenant_key=tenant)
    tid = created["thread_id"]
    for agent in joiners:
        await comm.join_thread(thread_id=tid, participant_id=agent, tenant_key=tenant)
    return tid


def _ids(turn) -> set[str]:
    return {t["thread_id"] for t in turn["threads"]}


# ---------------------------------------------------------------------------
# (A) terminal threads hold nobody's turn — BOTH arms
# ---------------------------------------------------------------------------


async def test_a_terminal_thread_drops_off_both_baton_arms(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    named = await _thread(comm, tenant, joiners=("lane-A",))
    broadcast = await _thread(comm, tenant, joiners=("lane-A",))
    await comm.pass_baton(thread_id=named, to="lane-A", tenant_key=tenant)
    await comm.pass_baton(thread_id=broadcast, to="all", tenant_key=tenant)

    assert {named, broadcast} <= _ids(await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant))

    for tid in (named, broadcast):
        await comm.post_to_thread(
            thread_id=tid, content="done", from_agent="EM", set_status="resolved", tenant_key=tenant
        )

    after = await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant)
    assert _ids(after).isdisjoint({named, broadcast})
    assert after["count"] == 0


# ---------------------------------------------------------------------------
# (B) 'all' means all PARTICIPANTS — and only the 'all' arm is narrowed
# ---------------------------------------------------------------------------


async def test_b_all_baton_reaches_participants_and_not_strangers(db_session):
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    tid = await _thread(comm, tenant, joiners=("lane-A",))
    await comm.pass_baton(thread_id=tid, to="all", tenant_key=tenant)

    # The participant still sees it — (B) narrows WHO 'all' reaches, it does not
    # stop 'all' from working. The poll surface is unchanged for them.
    assert tid in _ids(await comm.get_my_turn(agent_id="lane-A", tenant_key=tenant))
    # The stranger never joined this conversation and must not inherit its turn.
    assert tid not in _ids(await comm.get_my_turn(agent_id="lane-Z", tenant_key=tenant))


async def test_b_does_not_narrow_the_named_arm(db_session):
    """A NAMED baton must still surface without a participant row.

    Deliberately pinned: a human operator is reachable whether or not they ever
    spoke on a thread (``comm_baton_targets``: "the operator's my-turn view is
    per-user, not per-participation"). Adding the participation join to both arms
    would have been the easy over-reach and would silently strand hand-offs.
    """
    tenant = TenantManager.generate_tenant_key()
    await _seed_cht(db_session, tenant)
    comm = _comm(db_session)

    tid = await _thread(comm, tenant)
    # Straight to the repo: pass_baton screens unknown targets (BE-9292a), and the
    # shape under test is the STORED one — a baton naming someone with no row.
    from giljo_mcp.database import tenant_session_context

    with tenant_session_context(db_session, tenant):
        await comm._repo.set_next_action_owner(db_session, tenant, tid, "never-joined")

    assert tid in _ids(await comm.get_my_turn(agent_id="never-joined", tenant_key=tenant))


async def test_b_is_tenant_scoped(db_session):
    """The participation join must not become a cross-tenant leak."""
    t1, t2 = TenantManager.generate_tenant_key(), TenantManager.generate_tenant_key()
    await _seed_cht(db_session, t1)
    await _seed_cht(db_session, t2)
    comm = _comm(db_session)

    tid = await _thread(comm, t1, joiners=("lane-A",))
    await comm.pass_baton(thread_id=tid, to="all", tenant_key=t1)

    assert tid in _ids(await comm.get_my_turn(agent_id="lane-A", tenant_key=t1))
    assert (await comm.get_my_turn(agent_id="lane-A", tenant_key=t2))["count"] == 0


# The park gate itself is a pure function and is covered without a database in
# tests/unit/test_be9388_park_gate.py — the (C) truth table lives there.
