# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9348 — absorption that swallows an OPTIONAL argument was persisted silently.

TSK-9309 established the cause: a caller's tool-call serialization can merge one
argument into the string value of a neighbouring one, so the following argument never
leaves the caller. It installed a diagnosis at the MCP dispatch seam — but gated it
behind "a required argument is already absent":

    missing = [field for field in required if field not in arguments]
    if not missing:
        return None

That is the wrong precondition, and it leaves the WORSE half of the defect open. When
absorption swallows an argument that is merely OPTIONAL (``tags``, ``git_commits``),
all four required arguments are still present. Pydantic validates. The write boundary
caps length but does not reject call syntax. The closeout SUCCEEDS, the swallowed
argument is lost, and the caller's raw tool-call markup is written verbatim into a
permanent 360 memory row — with no error for anyone to react to.

Measured, not assumed:

* The server has no truncation boundary. Driven through this same real MCP transport,
  every parameter arrives byte-identical at 10 chars and at 2,000,000 chars alike.
  Nothing server-side drops or truncates anything; the loss is in the CALLER.
* At least 8 rows in the dogfood 360 memory already carry the residue, e.g. a summary
  ending ``...markdown-only commits, filed as INF-9293.</summary>\\n<parameter
  name="tags">["docs", "chore", "infrastructure"]`` with the row's own ``tags`` empty.

This is a mechanism gap, not a documentation one: a careful caller does everything
right and still gets a permanently wrong durable record.

The fix can only turn a currently-SUCCEEDING call into a rejection, so over-firing is
the entire risk. Two safety properties bound it, and both are pinned below:
``conclusive`` evidence only (the weak "ends with a JSON-list tail" signal may never
reject a valid call), and a residue tail that is ENTIRELY call syntax to end-of-string
(prose that merely quotes markup — such as the closeout written for this very project —
must pass untouched).

Parallel-safe: fresh tenant_key per test, rolled-back db_session, no module-level
mutable state, no ordering dependencies.
"""

from __future__ import annotations

import json
import random
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import func, select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor


def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The two real optional-absorption shapes, reproduced from live 360 memory rows.
# Both leave every REQUIRED argument present, which is why nothing rejected them.
# ---------------------------------------------------------------------------

# Shape T (360 memory seq 904, project INF-9283): `tags` absorbed; the row's own
# tags column is empty and the vocabulary values live inside the summary text.
_ABSORBED_TAGS_SUMMARY = (
    "Swept the remaining actively-referenced instructional surfaces and repaired every "
    "pointer, then closed the naming gap the earlier chain left behind."
    '</summary>\n<parameter name="tags">["docs", "chore", "infrastructure"]'
)

# Shape G (360 memory seq 433, project FE-6022b): `git_commits` absorbed, so the
# closeout recorded zero commits while the SHAs sat in the summary prose.
_ABSORBED_GIT_COMMITS_SUMMARY = (
    "Built the pane, bound it to the API, and shipped the drag-reorder rail. "
    "vitest 27/27, eslint clean, vite build clean."
    '</summary>\n<parameter name="git_commits">[{"sha": "7dafbb675", "message": '
    '"feat(roadmap): frontend pane"}]'
)

# Shape O (old-style tag, 360 memory seq 589, project BE-6198): same loss, tag syntax.
_ABSORBED_TAGS_OLD_STYLE_SUMMARY = (
    "Chain cold-start hardening landed and the live deadlock is gone."
    '</summary>\n<tags>["backend", "frontend", "bug-fix", "test"]'
)


@pytest_asyncio.fixture
async def closeout_mcp_client(db_manager, db_session, monkeypatch):
    """(client_factory, tenant_key, db_session) with write_project_closeout bound to
    the rolled-back test session — same lifecycle fixture as the TSK-9309 suite."""
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
        name=f"BE9348 Org {suffix}",
        slug=f"be9348-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"BE9348 Product {suffix}",
        description="BE-9348 optional argument absorption",
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
        name=f"BE9348 Project {suffix}",
        description="BE-9348",
        mission="Optional argument absorption regression",
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
# DoD 1 — an absorbed OPTIONAL argument must be rejected, and nothing written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "absorbing_summary", "absorbed_name"),
    [
        ("tags-parameter-tag", _ABSORBED_TAGS_SUMMARY, "tags"),
        ("git-commits-parameter-tag", _ABSORBED_GIT_COMMITS_SUMMARY, "git_commits"),
        ("tags-old-style-tag", _ABSORBED_TAGS_OLD_STYLE_SUMMARY, "tags"),
    ],
    ids=["tags-parameter-tag", "git-commits-parameter-tag", "tags-old-style-tag"],
)
@pytest.mark.asyncio
async def test_absorbed_optional_argument_is_rejected_and_writes_nothing(
    closeout_mcp_client, label, absorbing_summary, absorbed_name
):
    """Every REQUIRED argument is present, so nothing is "missing" — but the summary
    carries the caller's own tool-call syntax, which proves the optional argument was
    absorbed rather than omitted.

    RED before the fix: the closeout SUCCEEDS. A 360 memory row is written whose summary
    ends in raw tool-call markup, and the absorbed argument is silently lost. That bad
    permanent record is the whole reason this is worth fixing.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    before = await _memory_entry_count(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": absorbing_summary,
                "key_outcomes": ["The filter matches what rotation writes"],
                "decisions_made": ["Fixed at the rotation layer"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert result.isError, f"[{label}] an absorbed optional argument must be rejected, got: {text!r}"

    lowered = text.lower()
    assert absorbed_name in text, (
        f"[{label}] the rejection must name the optional argument that was absorbed ({absorbed_name}); got: {text!r}"
    )
    assert "summary" in lowered, (
        f"[{label}] the rejection must name the argument that absorbed it (summary); got: {text!r}"
    )
    assert any(word in lowered for word in ("absorb", "merged into", "did not arrive")), (
        f"[{label}] the rejection must state the argument was absorbed, not merely wrong; got: {text!r}"
    )

    after = await _memory_entry_count(session, tenant_key)
    assert after == before, f"[{label}] a rejected closeout must write no 360 entry (before={before}, after={after})"

    await session.refresh(project)
    assert project.status == "active", f"[{label}] a rejected closeout must not close the project: {project.status!r}"


# ---------------------------------------------------------------------------
# Two-sided half 1 — the WEAK signal may never reject an otherwise-valid call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legitimate_json_list_tail_still_succeeds(closeout_mcp_client):
    """A summary can legitimately END with a quoted JSON list — that tail is the
    weakest evidence available and is explicitly NOT conclusive.

    With nothing missing, this call is currently accepted, so rejecting it here would
    make the fix worse than the defect. Pinning it is the point.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": (
                    'Corrected the archive filter. The offending values were ["giljo.log.1", "giljo.log.2026-08-01"]'
                ),
                "key_outcomes": ["The filter now matches rotation output [verified on disk]"],
                "decisions_made": ["Matched the real filename shape, not the assumed one"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.isError, f"a summary legitimately ending in a JSON list must still succeed, got: {text!r}"
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"the 360 entry must still be written, got: {parsed!r}"


# ---------------------------------------------------------------------------
# Two-sided half 2 — prose that QUOTES markup mid-sentence must pass untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prose_quoting_tool_call_markup_still_succeeds(closeout_mcp_client):
    """The closeout written for THIS project will necessarily quote the very tags the
    detector looks for. Absorption always leaves a tail that is pure call syntax to
    end-of-string; prose quoting markup continues in ordinary sentences afterwards.

    That distinction is the tail-narrowing safety property, and this is the test that
    makes it load-bearing rather than decorative.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": (
                    "A caller's serializer sometimes merges an argument into its neighbour, so a "
                    "summary would end with a <tags> marker followed by a JSON array. The server now "
                    "refuses that call at the dispatch seam instead of storing the markup, and says "
                    "which argument was absorbed."
                ),
                "key_outcomes": ["Absorbed optional arguments are refused, not persisted"],
                "decisions_made": ["Rejected only on conclusive evidence with a pure call-syntax tail"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.isError, f"prose that merely quotes tool-call markup must still succeed, got: {text!r}"
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"the 360 entry must still be written, got: {parsed!r}"


# ---------------------------------------------------------------------------
# Two-sided half 3 — an angle-bracket PLACEHOLDER is prose, not absorption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "summary"),
    [
        ("cli-usage", "Documented the CLI entry point. Usage: giljo close <project_id>"),
        ("route-list", "Added the read routes:\n- GET /api/projects/<project_id>"),
        ("trailing-comma", "The archive filter now interpolates <project_id>,"),
        ("trailing-period", "The archive filter now interpolates <project_id>."),
        ("bare-placeholder-eos", "The archive filter now interpolates <project_id>"),
        ("optional-param-placeholder", "Documented the closeout call. Pass the vocabulary in <tags>"),
    ],
    ids=[
        "cli-usage",
        "route-list",
        "trailing-comma",
        "trailing-period",
        "bare-placeholder-eos",
        "optional-param-placeholder",
    ],
)
@pytest.mark.asyncio
async def test_angle_bracket_placeholder_in_prose_still_succeeds(closeout_mcp_client, label, summary):
    """A summary ending in an angle-bracket placeholder must still be ACCEPTED.

    ``<project_id>``, ``<name>`` and ``<title>`` are all real parameter names on this
    tool surface (117 of them across 46 tools, including 'name', 'title', 'status',
    'description'), so ``_absorption_residue`` calls every one of these conclusive.
    The only thing standing between ordinary prose and a refusal is the requirement
    that the tail carry an actual serialized VALUE — a real absorption leaves
    ``["docs", "chore"]`` behind, a placeholder leaves nothing.

    RED before the value-opener guard: stripping the tag reduced the tail to empty,
    which satisfied "pure call syntax" vacuously, and these were all refused while
    master accepted every one. ``trailing-comma`` is the sharp case — the weaker fix
    of "tail must be non-empty after tag removal" still fails it, because the lone
    comma is then eaten by the JSON-punctuation strip.

    This is the regression that a future edit would otherwise reintroduce silently:
    the original 13 tests pass with OR without the guard.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": summary,
                "key_outcomes": ["The placeholder is prose, not an absorbed argument"],
                "decisions_made": ["Required a serialized value before claiming absorption"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert not result.isError, (
        f"[{label}] an angle-bracket placeholder in ordinary prose must NOT be read as absorption "
        f"-- master accepts this call; got: {text!r}"
    )
    parsed = json.loads(text)
    assert parsed.get("entry_id"), f"[{label}] the 360 entry must still be written, got: {parsed!r}"


# ---------------------------------------------------------------------------
# A value is not always bracketed — bare SCALAR absorption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "absorbed_tail"),
    [
        ("integer", '<parameter name="force">3'),
        ("boolean", '<parameter name="force">true'),
        ("null", '<parameter name="force">null'),
    ],
    ids=["integer", "boolean", "null"],
)
@pytest.mark.asyncio
async def test_absorbed_bare_scalar_argument_is_rejected(closeout_mcp_client, label, absorbed_tail):
    """A scalar-valued parameter is absorbed as a bare token, not a bracketed list.

    The first cut of this guard tested for a value OPENER (``[``, ``{``, ``"``), which is
    exactly wrong for ``<parameter name="phase">3`` — 15 string→scalar adjacencies exist
    on the live tool surface, so these were persisted silently. Pre-existing rather than
    introduced here: this shape also slipped through the previous two revisions.

    Bare scalars only count under the serializer's own ``<parameter name="...">`` markup;
    a hand-written prose placeholder is ``<project_id>``, never that form. Without that
    condition the guard would refuse "...<project_id> 2026", which is why the placeholder
    cases above are the other half of this pair.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    before = await _memory_entry_count(session, tenant_key)

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": "Closed the lane and pinned the regression.</summary>\n" + absorbed_tail,
                "key_outcomes": ["The scalar was absorbed, not omitted"],
                "decisions_made": ["Gated the scalar allowance on the serializer's own markup"],
            },
        )

    text = _content_text(result)
    assert result.isError, f"[{label}] an absorbed bare scalar must be rejected, got: {text!r}"
    assert "force" in text, f"[{label}] the rejection must name the absorbed argument: {text!r}"

    after = await _memory_entry_count(session, tenant_key)
    assert after == before, f"[{label}] a rejected closeout must write no 360 entry"


# ---------------------------------------------------------------------------
# Two-sided half 4 — TSK-9309's required-argument path must not regress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_be9348_prod_shape_still_names_absorption(closeout_mcp_client):
    """The shape that actually produced the five reported prod failures: `summary`
    absorbed `key_outcomes` and `decisions_made`, so those two ARE missing.

    This is TSK-9309's path and it must keep working exactly as before — the fix
    decouples the residue scan from the missing-required gate, it does not replace it.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    absorbing_summary = (
        "Reworded the archive filter so it matches what rotation actually writes. "
        'The regression test pins the real filename shape."]</key_outcomes>\n'
        '<decisions_made>["Matched the real shape"]</decisions_made>\n'
    )

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": absorbing_summary},
        )

    text = _content_text(result)
    assert result.isError, f"expected rejection, got: {text!r}"
    assert "key_outcomes" in text, f"the rejection must name the absorbed required field: {text!r}"
    assert "absorb" in text.lower(), f"the rejection must name absorption as the cause: {text!r}"


@pytest.mark.asyncio
async def test_genuine_omission_still_gets_the_plain_validation_error(closeout_mcp_client):
    """A caller that simply forgot the required arguments — clean summary, no residue —
    must keep the ordinary validation error. Claiming absorption here would name a cause
    that is not the real one, which is the defect this whole diagnosis exists to correct.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {"project_id": project.id, "summary": "Short and clean prose with no residue."},
        )

    text = _content_text(result)
    assert result.isError, f"a missing required field must still be rejected, got: {text!r}"
    assert "key_outcomes" in text, f"the rejection must name the missing field, got: {text!r}"
    assert "absorb" not in text.lower(), f"a genuine omission must NOT be reported as absorption: {text!r}"


# ---------------------------------------------------------------------------
# The size question the filing raised — answered at the SERVER side only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_large_payload_arrives_whole_at_the_server(closeout_mcp_client):
    """PROVES: the SERVER receives a large argument payload intact — every parameter
    present, the long value not truncated.

    DOES NOT PROVE — and cannot — that the CALLER serializes it correctly. The reported
    truncation happens in the caller's tool-call serialization, before the wire, which no
    server-side test can reach. This test exists to keep "the server has a size limit"
    permanently falsified, because that theory cost one real session eight tool calls.

    A 180,000-character summary is far above the documented 1500-char cap, so the honest
    server answer is the CAP rejection — and that error reports the length it actually
    received. `actual=180000` in the message is the measurement: all 180,000 characters
    crossed the transport. A truncating transport could not produce that number, and a
    dropped parameter would have produced "Field required" instead.
    """
    client, tenant_key, session = closeout_mcp_client
    project = await _seed_project(session, tenant_key)
    await session.commit()

    oversized_summary = "S" * 180_000

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_project_closeout",
            {
                "project_id": project.id,
                "summary": oversized_summary,
                "key_outcomes": ["o" * 200, "second outcome"],
                "decisions_made": ["d" * 200],
                "tags": ["backend", "bug-fix"],
                "force": True,
            },
        )

    text = _content_text(result)
    assert result.isError, f"a 180 KB summary is over the documented cap and must be rejected, got: {text!r}"
    assert "180000" in text, (
        "the cap rejection must report the length the server actually received -- "
        f"if the transport truncated, this number would be smaller; got: {text!r}"
    )
    assert "Field required" not in text, (
        f"every parameter must have arrived; a missing one would mean the payload was mangled: {text!r}"
    )
