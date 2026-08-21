# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9450 — the absorption rejection sent callers to a remedy that does not work.

TSK-9309 and BE-9348 built the absorption diagnosis, and the DETECTION is correct:
when a caller's tool-call serialization merges one argument into the string value of
a neighbouring one, the server says so and writes nothing. That part stays, and the
museum rule applies to it — none of these tests touch it.

What was wrong is one sentence of ADVICE at the end of both rejection messages:

    "Re-send the call with a SHORTER '{param}' so the next argument boundary is not
    swallowed."

Shortening does not fix it, and the message contradicts itself by saying so two
clauses earlier ("no server-side payload limit was reached"). The operator's record
is a caller that went 1,725 -> 302 characters across seven attempts and failed every
time, and a later session that went 2,674 -> 1,143 and failed again.

Measured here rather than asserted (`test_the_remedy_premise_*` below): the absorbed
shape is rejected identically at 2,930 characters and at 88, while a clean 1,400-character
summary with NOTHING serialized after it is accepted. Length is not the variable.
ORDER is — absorption swallows whatever FOLLOWS the long field, so putting that field
LAST leaves nothing to swallow.

``summary`` does carry a genuine 1500-character service-layer cap, enforced after
dispatch. So the claim is deliberately "an 88-character absorbed call is refused while
a 1,400-character clean one is accepted", NOT "accepted at a greater length than the
longest rejected call" — the cap makes that second version unmeasurable, and an earlier
draft of this work asserted it by probing the message function directly, upstream of the
cap. The 88-vs-1,400 comparison needs no such caveat and is sufficient.

These tests pin the remedy WORDING at the layer the message is produced and observed
— the MCP transport boundary — so the advice cannot silently regress to a length
remedy. They deliberately assert on the message's meaning (reorder / last, and the
absence of a shortening instruction), not on its exact prose.

Parallel-safe: fresh tenant_key per test, rolled-back db_session, no module-level
mutable state, no ordering dependencies.
"""

from __future__ import annotations

import random
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The absorbed shapes, built as a template so the SAME shape can be driven at
# very different lengths. That is the whole measurement: only the prose length
# varies between the long and short variants below.
# ---------------------------------------------------------------------------


def _required_path_summary(prose: str) -> str:
    """Shape A: the tail of the whole tool call collapsed into ``summary``, so the
    REQUIRED ``key_outcomes`` never arrived as its own argument."""
    return (
        prose + "</summary>\n"
        '<key_outcomes>["The lane landed", "The gate is live again"]</key_outcomes>\n'
        '<tags>["backend", "chore"]</tags>\n'
        "</invoke>\n"
    )


def _optional_path_summary(prose: str) -> str:
    """Shape B: every REQUIRED argument arrived; only the optional ``tags`` was
    absorbed. Before BE-9348 this call was accepted and the markup persisted."""
    return prose + '<parameter name="tags">["backend", "chore"]'


# Two lengths of the same shape, an order of magnitude apart.
_LONG_PROSE = "Closed the lane and re-armed the guard. " * 70
_SHORT_PROSE = "Done."

# EVERY required argument of write_project_closeout except the absorbing `summary`.
# The optional path is defined by nothing required being absent, so an incomplete set
# here silently routes the call to the REQUIRED message instead — which looks like a
# passing optional-path test while never once exercising the optional message. That
# happened on the first draft of this file: `decisions_made` was missing, both
# parametrized cases ran the required path, and the optional wording went untested.
_ALL_REQUIRED_BESIDES_SUMMARY = {
    "key_outcomes": ["The lane landed"],
    "decisions_made": ["Reworded the remedy instead of touching the detector"],
}


@pytest_asyncio.fixture
async def closeout_mcp_client(db_manager, db_session, monkeypatch):
    """(client_factory, tenant_key, db_session) with write_project_closeout bound to
    the rolled-back test session — same lifecycle fixture as the TSK-9309/BE-9348
    suites."""
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.project_closeout import close_project_and_update_memory

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    async def _closeout_with_session(tenant_key: str, **kwargs: Any) -> dict[str, Any]:
        return await close_project_and_update_memory(
            tenant_key=tenant_key,
            db_manager=db_manager,
            session=db_session,
            **kwargs,
        )

    accessor.write_project_closeout = _closeout_with_session
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_project(db_session, tenant_key: str) -> Project:
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"TSK9450 Org {suffix}",
        slug=f"tsk9450-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"TSK9450 Product {suffix}",
        description="TSK-9450 absorption remedy wording",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"TSK9450 Project {suffix}",
        description="TSK-9450",
        mission="Absorption remedy wording regression",
        status="active",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _memory_entry_count(db_session, tenant_key: str) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(ProductMemoryEntry).where(ProductMemoryEntry.tenant_key == tenant_key)
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# The instrument check. These two must pass on BOTH sides of the change — before
# the wording fix and after it. If they go red, the harness is broken and every
# RED below proves nothing about the message.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_instrument_absorbed_call_is_still_rejected(closeout_mcp_client):
    """Detection is TSK-9309/BE-9348 work and is deliberately untouched. If this
    fails, the reproduction harness is broken, not the remedy wording."""
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": _required_path_summary(_LONG_PROSE)},
        )

    text = _content_text(result)
    assert result.is_error, f"an absorbed-argument call must still be rejected, got: {text!r}"
    assert "absorb" in text.lower(), f"the rejection must still name absorption as the cause, got: {text!r}"


@pytest.mark.asyncio
async def test_instrument_well_formed_call_still_succeeds(closeout_mcp_client):
    """The other side of the instrument: a correct call still reaches the tool. A
    change that stops accepting real closeouts would make every RED here meaningless."""
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane. " + ("Long but entirely legitimate prose. " * 40),
                "key_outcomes": ["Shipped the wording fix"],
                "decisions_made": ["Reworded the remedy instead of touching the detector"],
                "force": True,
            },
        )

    assert not result.is_error, f"a well-formed closeout must still succeed, got: {_content_text(result)!r}"


# ---------------------------------------------------------------------------
# The measurement that justifies changing the advice. Not taken on faith from
# the task filing — driven here, at the boundary, at two very different lengths.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "build", "extra_args"),
    [
        ("required-path", _required_path_summary, {}),
        ("optional-path", _optional_path_summary, _ALL_REQUIRED_BESIDES_SUMMARY),
    ],
    ids=["required-path", "optional-path"],
)
@pytest.mark.asyncio
async def test_the_remedy_premise_shortening_does_not_help(closeout_mcp_client, label, build, extra_args):
    """Length is not the variable, so a length remedy cannot be the right advice.

    The SAME absorbed shape is rejected at both lengths. This is the observation the
    wording change rests on: if shortening helped at some length, the short variant
    would be accepted here and the whole premise — and this lane — would be wrong.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    long_summary = build(_LONG_PROSE)
    short_summary = build(_SHORT_PROSE)
    assert len(long_summary) > 10 * len(short_summary), (
        f"[{label}] the two variants must differ by an order of magnitude for this to measure "
        f"anything (long={len(long_summary)}, short={len(short_summary)})"
    )

    for size_label, summary in (("long", long_summary), ("short", short_summary)):
        async with client() as mcp_session:
            result = await mcp_session.call_tool(
                "write_project_closeout",
                {"project_id": project.id, "summary": summary, **extra_args},
            )
        text = _content_text(result)
        assert result.is_error, (
            f"[{label}/{size_label}] the absorbed shape must be rejected at {len(summary)} characters too — "
            f"if shortening fixed absorption, this call would have succeeded: {text!r}"
        )


@pytest.mark.asyncio
async def test_the_remedy_premise_putting_the_long_field_last_works(closeout_mcp_client):
    """The other half of the measurement, and the remedy the message must now teach.

    A summary many times LONGER than the shortest rejected one is accepted, because
    nothing was serialized after it and so nothing could be swallowed. Length is not
    the variable; what follows the field is.

    The comparison is deliberately against the SHORT absorbed variant. ``summary`` does
    carry a real service-layer cap (1500 characters, enforced after dispatch and
    reported as ``validation_failed: summary actual=... max=1500``), so "accepted at a
    greater length than the longest rejected call" is not available to measure and is
    not what this claims. The point stands without it: an 88-character absorbed call is
    refused while a clean summary an order of magnitude longer sails through, so size is
    not what the absorption rejection is reacting to.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    # Comfortably inside the documented 1500-character cap, so an acceptance here is
    # about absorption and not about the cap.
    reordered_summary = "Closed the lane and re-armed the guard. " * 35
    shortest_rejected = len(_required_path_summary(_SHORT_PROSE))
    assert len(reordered_summary) > 10 * shortest_rejected, (
        f"the accepted summary must dwarf the shortest REJECTED one or this measures nothing "
        f"(accepted={len(reordered_summary)}, shortest rejected={shortest_rejected})"
    )

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "key_outcomes": ["The lane landed"],
                "decisions_made": ["Sent summary last so nothing could be absorbed into it"],
                "tags": ["backend", "chore"],
                # summary LAST: nothing follows it, so nothing can be absorbed into it.
                "summary": reordered_summary,
                "force": True,
            },
        )

    assert not result.is_error, (
        f"a {len(reordered_summary)}-character summary with nothing serialized after it must be "
        f"ACCEPTED — that is the remedy the rejection is supposed to teach: {_content_text(result)!r}"
    )


# ---------------------------------------------------------------------------
# DoD 1 + 2 — the remedy must be reordering, and must not contradict itself
# ---------------------------------------------------------------------------

# Every imperative form of the remedy that does not work. Deliberately the
# INSTRUCTION phrasings and not a bare "shorter": the corrected message names
# shortening in order to rule it out ("making 'summary' shorter will NOT help"), and a
# blunt substring ban cannot tell an instruction from its negation. Banning the bare
# word would forbid the one clause that closes the dead end.
_SHORTENING_INSTRUCTIONS = (
    "with a shorter",
    "use a shorter",
    "send a shorter",
    "try a shorter",
    "shorten",
    "trim ",
    "truncate",
    "fewer characters",
)

# The corrected message must close the dead end explicitly, not merely omit it. An
# agent that has met the old wording will try shortening first unless told plainly
# that it does not work — the operator's record is seven such retries in a row.
_DEAD_END_CLOSED = "shorter will not help"


@pytest.mark.parametrize(
    ("label", "build", "extra_args", "absorbed_name"),
    [
        ("required-path", _required_path_summary, {}, "key_outcomes"),
        ("optional-path", _optional_path_summary, _ALL_REQUIRED_BESIDES_SUMMARY, "tags"),
    ],
    ids=["required-path", "optional-path"],
)
@pytest.mark.asyncio
async def test_rejection_recommends_reordering_not_shortening(
    closeout_mcp_client, label, build, extra_args, absorbed_name
):
    """Both rejection paths must teach the remedy that works: put the long free-text
    field LAST so nothing follows it. Neither may tell the caller to shorten it.

    RED before fix: both messages end "Re-send the call with a SHORTER 'summary'".
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": build(_LONG_PROSE), **extra_args},
        )

    text = _content_text(result)
    lowered = text.lower()
    assert result.is_error, f"[{label}] expected a rejection, got: {text!r}"

    for instruction in _SHORTENING_INSTRUCTIONS:
        assert instruction not in lowered, (
            f"[{label}] the rejection must NOT prescribe a length remedy ({instruction!r}) — shortening "
            f"does not fix absorption, and this advice cost one caller seven failed retries: {text!r}"
        )

    assert _DEAD_END_CLOSED in lowered, (
        f"[{label}] the rejection must state outright that shortening will not help — omitting the "
        f"instruction is not enough when the previous message trained callers to shorten: {text!r}"
    )
    assert "last" in lowered, (
        f"[{label}] the rejection must tell the caller to send 'summary' LAST — that is the remedy that "
        f"works, because nothing follows it and so nothing can be swallowed: {text!r}"
    )
    assert any(word in lowered for word in ("reorder", "order", "last argument", "after it")), (
        f"[{label}] the rejection must frame the remedy as argument ORDER, not size: {text!r}"
    )

    # The parts that already worked and must survive the rewording.
    assert "summary" in lowered, f"[{label}] the rejection must still name the absorbing argument: {text!r}"
    assert absorbed_name in text, f"[{label}] the rejection must still name the absorbed argument: {text!r}"
    assert "nothing was written" in lowered, (
        f"[{label}] the 'Nothing was written' reassurance must survive the rewording — it is what stops the "
        f"caller hunting for a half-written record: {text!r}"
    )


@pytest.mark.parametrize(
    ("label", "build", "extra_args"),
    [
        ("required-path", _required_path_summary, {}),
        ("optional-path", _optional_path_summary, _ALL_REQUIRED_BESIDES_SUMMARY),
    ],
    ids=["required-path", "optional-path"],
)
@pytest.mark.asyncio
async def test_rejection_does_not_contradict_itself(closeout_mcp_client, label, build, extra_args):
    """The message correctly states no payload limit was reached. It must not then
    prescribe a remedy that only makes sense if one had been.

    RED before fix: the message says both, in consecutive sentences.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": build(_LONG_PROSE), **extra_args},
        )

    text = _content_text(result)
    lowered = text.lower()
    assert result.is_error, f"[{label}] expected a rejection, got: {text!r}"
    assert "payload limit was reached" in lowered, (
        f"[{label}] the message must keep stating that no payload limit was reached — it is true and it is "
        f"what stops the caller hunting for a cap to raise: {text!r}"
    )
    assert not any(instruction in lowered for instruction in _SHORTENING_INSTRUCTIONS), (
        f"[{label}] a message that states no size limit was hit cannot also prescribe a size remedy — that "
        f"self-contradiction is the defect: {text!r}"
    )


# ---------------------------------------------------------------------------
# DoD 4 — the sibling surface. Verified by driving a SECOND tool through the
# boundary, not assumed from the shared call site.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sibling_tool_write_memory_entry_gets_the_same_remedy(closeout_mcp_client):
    """``write_memory_entry`` has the identical shape — an uncapped free-text
    ``summary`` followed by four list arguments — and is the other tool the operator
    lost 360 memory through.

    The rejection is produced by one shared, schema-driven code path
    (``mcp_sdk_server._describe_absorbed_argument_for``), so fixing the two messages
    should cover it. This test proves that rather than assuming it: if the wording
    were ever forked per tool, this goes red.
    """
    client, _tenant_key, _session = closeout_mcp_client

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_memory_entry",
            {
                "summary": _required_path_summary(_LONG_PROSE),
                "entry_type": "learning",
            },
        )

    text = _content_text(result)
    lowered = text.lower()
    assert result.is_error, f"an absorbed write_memory_entry call must be rejected, got: {text!r}"
    assert "absorb" in lowered, f"the rejection must name absorption, got: {text!r}"
    for instruction in _SHORTENING_INSTRUCTIONS:
        assert instruction not in lowered, (
            f"write_memory_entry must get the corrected remedy too ({instruction!r} found): {text!r}"
        )
    assert "last" in lowered, f"write_memory_entry must be told to send 'summary' LAST: {text!r}"


# ---------------------------------------------------------------------------
# Unchanged behaviour — the reworded message must not become a new false positive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_genuine_omission_still_gets_the_plain_validation_error(closeout_mcp_client):
    """A caller that simply forgot key_outcomes keeps the ordinary validation error.
    Naming absorption here would be the original defect in the opposite direction."""
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": "Short and clean prose with no residue."},
        )

    text = _content_text(result)
    assert result.is_error, f"a missing required field must still be rejected, got: {text!r}"
    assert "key_outcomes" in text, f"the rejection must name the missing field, got: {text!r}"
    assert "absorb" not in text.lower(), f"a genuine omission must not be reported as absorption: {text!r}"


@pytest.mark.asyncio
async def test_rejected_call_still_writes_nothing(closeout_mcp_client):
    """The reason this defect mattered: a bad permanent record. Rewording the advice
    must not disturb the reject-before-write ordering."""
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    before = await _memory_entry_count(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": _required_path_summary(_LONG_PROSE)},
        )

    assert result.is_error, f"expected rejection, got: {_content_text(result)!r}"
    after = await _memory_entry_count(session, tenant_key)
    assert after == before, f"a rejected closeout must write no 360 entry (before={before}, after={after})"

    await session.refresh(project)
    assert project.status == "active", f"a rejected closeout must not close the project, got: {project.status!r}"
