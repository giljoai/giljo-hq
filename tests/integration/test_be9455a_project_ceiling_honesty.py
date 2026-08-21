# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9455 Symptom A — the agent-facing project list truncates on the wrong axis, silently.

Symptom the operator reported: a real ``list_projects`` call from the claude.ai web
client returned a list that looked complete while 145 COMPLETED projects were absent
from it. Two defects compound:

1. **The cut is ordered by the wrong column.** ``list_projects_for_mcp`` passes
   ``limit=_MCP_LIST_PROJECT_CEILING`` and no sort, so ``project_repository`` applies
   its limit-fallback order ``created_at DESC, id ASC``. The ceiling therefore keeps
   the newest-**created** N. A project created long ago and completed yesterday falls
   outside the window and **disappears** -- which is the shape of every hidden row on
   the ticket (created 2026-04-13, completed June/July). A defensive cap must never
   silently select on a different axis from the caller's question.
2. **Truncation is invisible to the caller.** The cap-hit branch logged a ``warning``
   and returned a response with no flag, no count, no note. An agent asking "what did
   we ship" reasoned over a truncated list as if it were complete, so every downstream
   answer was confidently wrong. A client agent in the operator's session detected the
   mis-ordering and compensated for it -- and could not detect what was already missing.

FAIL-FIRST (measured on base master ``5a3ce2ab1``, unpatched):

* ``test_the_newest_completion_survives_the_ceiling`` fails on the presence assertion
  -- the most recently completed project is ABSENT from a completion-oriented list.
* ``test_a_truncated_response_says_so`` fails on ``truncated`` -- the key does not exist.
* ``test_a_completion_oriented_list_is_ordered_by_completion`` fails on the ordering.
* ``test_the_ceiling_clears_the_measured_floor`` fails -- the ceiling was 1000.

``test_an_untruncated_response_says_it_was_not_truncated`` and
``test_the_default_active_list_still_truncates_on_creation`` are the both-sides guards:
they must pass BEFORE and AFTER the fix. If they go red, the instrument is broken and
the RED above proves nothing.

**The ceiling is patched to a small value rather than seeded past.** The constant IS
the mechanism, so a 5-row dataset against a ceiling of 4 exercises the identical code
path an over-ceiling dataset would at production scale -- deterministically, in
milliseconds, and without a CI test that has to be re-tuned every time the ceiling
moves. It also proves the more important thing: the ceiling VALUE is not what fixes
this. The newest completion survives a cap of 4, so it survives any cap.

The real-scale runs were done separately and recorded on BE-9455 -- 1,001 rows against
the old 1000 ceiling (target absent, no signal) and one row over the new ceiling (target
present at position 0, ``truncated`` true with its detail block) -- along with the
latency and payload measurements that picked the number. They are not committed: a test
that seeds past the shipped ceiling would have to be re-tuned whenever the ceiling moves
and would cost minutes per CI run to assert what the 5-row case already asserts.

Transport: the REAL ``@mcp.tool`` transport via ``create_connected_server_and_client_session``
against the real Postgres test DB -- the boundary the operator's client actually hit,
per the house rule that a bug gets a test at the layer it lived on.

Parallel-safe: each test generates a fresh ``tenant_key`` and purges its own rows in a
``finally`` block -- these MCP-adapter calls commit for real via ``db_manager``, so
there is no rollback isolation to lean on. No module-level mutable state, no ordering
dependencies. Edition Scope: Both.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import _mcp_adapter_query_mixin as ceiling_mod
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


# The floor the ceiling must clear, from the measurement recorded on BE-9455 (seeded
# data in a test database, NOT production): 297 KB / ~74k tokens at 1,147 rows, 650 KB /
# ~163k at 2,500, 1.30 MB / ~326k at 5,000. The binding constraint is response SIZE, not
# latency -- this list is agent-facing, so a payload that overflows the caller's context
# window is a second silent failure, and it takes the truncation flag down with it.
# 2,500 sits inside a 200k window; 5,000 does not. The tenant that reported the bug is
# stated on the ticket at 1,147 project rows -- that figure is the ticket's, not this
# suite's, and the ceiling is deliberately not set to merely clear it. Raising it needs
# a response-size ceiling first (the pattern exists as RESPONSE_CHAR_CEILING in
# tools/context_tools/_response_ceiling.py). This constant is the ratchet: it fails if
# the ceiling is ever lowered back toward a reported row count without the reasoning.
MEASURED_CEILING_FLOOR = 2500


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _content_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def mcp_client(db_manager, monkeypatch):
    """Wire a real ToolAccessor into the in-memory MCP transport.

    No injected test session: every tool call opens its own real session, exactly as
    it does in production. Yields ``(client_factory, tenant_key)``.
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
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def _iso(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T12:00:00+00:00")


async def _seed(db_manager, tenant_key: str, rows: list[dict]) -> str:
    """Commit one active product plus the given project rows. Returns the product id.

    Each row dict carries ``name``, ``created``, ``completed`` (a ``YYYY-MM-DD`` string
    or None) and ``status``. ``series_number`` is assigned sequentially so the
    ``uq_project_taxonomy_active`` NULLS-NOT-DISTINCT index cannot collide.
    """
    product_id = str(uuid.uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9455A Product {uuid.uuid4().hex[:6]}",
                description="BE-9455 Symptom A -- the agent-facing project ceiling.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        for index, row in enumerate(rows, start=1):
            session.add(
                Project(
                    id=row["id"],
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name=row["name"],
                    description="Seeded for the ceiling reproduction.",
                    mission="Prove the cut selects on the axis the caller asked about.",
                    status=row["status"],
                    staging_status="staging_complete",
                    series_number=index,
                    created_at=_iso(row["created"]),
                    completed_at=_iso(row["completed"]) if row.get("completed") else None,
                )
            )
        await session.commit()

    return product_id


def _completion_dataset() -> tuple[str, list[dict]]:
    """Four filler completions plus THE target: oldest-created, newest-completed.

    This is the production shape reduced to five rows. Under a ``created_at DESC`` cut
    the target is row five and vanishes; under a ``completed_at DESC`` cut it is row one.
    """
    target_id = str(uuid.uuid4())
    rows = [
        {
            "id": str(uuid.uuid4()),
            "name": f"filler newest-created {n}",
            "created": f"2026-08-0{n}",
            "completed": f"2026-05-0{n}",
            "status": "completed",
        }
        for n in (1, 2, 3, 4)
    ]
    rows.append(
        {
            "id": target_id,
            "name": "OLD-created, MOST-RECENTLY-completed",
            "created": "2026-04-13",
            "completed": "2026-07-13",
            "status": "completed",
        }
    )
    return target_id, rows


async def _list_projects(client, **kwargs) -> object:
    """Invoke the agent-facing ``list_projects`` @mcp.tool over the real transport."""
    async with client() as mcp_session:
        return await mcp_session.call_tool("list_projects", kwargs)


class TestTheCeilingKeepsTheRowsTheCallerAskedAbout:
    async def test_the_newest_completion_survives_the_ceiling(self, mcp_client, db_manager, monkeypatch):
        """THE regression. The most recently completed project must not be absent.

        Not "last in the list" -- absent from it. That absence is the whole bug: the
        response is a plausible-looking list an agent reasons over as complete.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            result = await _list_projects(client, include_completed=True)
            assert not result.is_error, f"the list must not error. content: {_content_text(result)!r}"
            payload = _payload(result)
            returned = [p["project_id"] for p in payload["projects"]]

            assert target_id in returned, (
                "the most recently completed project is ABSENT from a completion-oriented "
                "list -- the cap kept the newest-CREATED rows and dropped the newest-COMPLETED "
                f"one. returned {len(returned)} of {len(rows)} seeded rows: {returned!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_completion_oriented_list_is_ordered_by_completion(self, mcp_client, db_manager, monkeypatch):
        """The order the cap selects on must be the order the caller gets.

        A client agent in the operator's own session reported the returned order did not
        match completion time and re-sorted the list itself. Pinning the ordering here is
        what makes the truncation window defensible: the rows kept are the newest
        completions, in that order, on the caller's own axis.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 50)
        target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))
            returned = [p["project_id"] for p in payload["projects"]]

            assert returned[0] == target_id, (
                "a completion-oriented list must lead with the most recent completion "
                f"(2026-07-13); got order {[p['name'] for p in payload['projects']]!r}"
            )
            completions = [p["completed_at"] for p in payload["projects"]]
            assert completions == sorted(completions, reverse=True), (
                f"completion dates must descend, got {completions!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_a_mixed_query_never_drops_unfinished_work(self, mcp_client, db_manager, monkeypatch):
        """The MIRROR-IMAGE bug, and the only test that distinguishes this fix from the wrong one.

        ``include_completed=True`` asks for active work AND archived work, so the cap has
        to choose between them. The obvious implementation of this fix -- reuse the
        whitelisted ``completed_at`` sort key -- orders NULLS LAST like every entry in
        ``_SORT_COLUMNS``, which puts unfinished projects (``completed_at IS NULL``) at the
        BACK. On a tenant over the ceiling that spends the entire budget on finished rows
        and silently drops the ACTIVE projects: the reported bug, pointed the other way,
        and worse, because active work is what an agent needs most.

        ``completed_at DESC NULLS FIRST`` makes unfinished work un-droppable and lets the
        cap fall on the OLDEST completions -- the only bucket where "older" honestly means
        "less wanted". This test fails on master (creation order drops the unfinished rows
        for being oldest-created) and would also fail a NULLS LAST implementation, which is
        the whole reason it exists: the claim was argued in a commit message before
        anything verified it.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 3)
        unfinished = [
            {
                "id": str(uuid.uuid4()),
                "name": f"UNFINISHED created 2026-01-0{n}",
                "created": f"2026-01-0{n}",
                "completed": None,
                "status": "inactive",
            }
            for n in (1, 2)
        ]
        completed = [
            {
                "id": str(uuid.uuid4()),
                "name": f"completed 2026-07-0{n}",
                "created": f"2026-08-0{n}",
                "completed": f"2026-07-0{n}",
                "status": "completed",
            }
            for n in (1, 2, 3, 4)
        ]
        await _seed(db_manager, tenant_key, unfinished + completed)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))
            returned = {p["project_id"] for p in payload["projects"]}

            for row in unfinished:
                assert row["id"] in returned, (
                    "a mixed query must never drop unfinished work -- the cap has to fall on "
                    f"old completions, not on active projects. {row['name']!r} is absent; "
                    f"returned {[p['name'] for p in payload['projects']]!r}"
                )
            assert completed[3]["id"] in returned, (
                "the newest completion must survive alongside the unfinished work; "
                f"returned {[p['name'] for p in payload['projects']]!r}"
            )
            assert completed[0]["id"] not in returned, (
                "the OLDEST completion is what the cap should have discarded; "
                f"returned {[p['name'] for p in payload['projects']]!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_explicit_completed_status_query_is_completion_oriented_too(
        self, mcp_client, db_manager, monkeypatch
    ):
        """``status="completed"`` asks the same question as ``include_completed`` and must cut the same way.

        This is the narrower query an agent uses for "what did we ship", and on the
        test-install tenant it is over the ceiling on its own (1,069 completed rows).
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, status="completed"))
            returned = [p["project_id"] for p in payload["projects"]]
            assert target_id in returned, f"status='completed' dropped the newest completion. returned: {returned!r}"
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_the_default_active_list_still_truncates_on_creation(self, mcp_client, db_manager, monkeypatch):
        """BOTH-SIDES GUARD + the non-completion-oriented contract.

        The default agent view asks about ACTIVE projects, whose ``completed_at`` is NULL,
        so creation recency is the only meaningful axis and the cap must keep using it.
        This test passes before and after the fix; if it goes red the change leaked into
        a query it was never about.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 3)
        # ``inactive``, not ``active``: ``idx_project_single_active_per_product`` permits
        # exactly ONE active project per product (Handover 0050b), and both statuses are
        # in the agent list's default lifecycle-active view, so ``inactive`` exercises the
        # same non-completion-oriented path without fighting an unrelated invariant.
        rows = [
            {
                "id": str(uuid.uuid4()),
                "name": f"unfinished created 2026-08-0{n}",
                "created": f"2026-08-0{n}",
                "completed": None,
                "status": "inactive",
            }
            for n in (1, 2, 3, 4, 5)
        ]
        newest_three = {rows[4]["id"], rows[3]["id"], rows[2]["id"]}
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client))
            returned = {p["project_id"] for p in payload["projects"]}
            assert returned == newest_three, (
                "an active-only list must still keep the newest-CREATED rows -- "
                f"expected the three newest, got {[p['name'] for p in payload['projects']]!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTruncationIsVisibleToTheCaller:
    async def test_a_truncated_response_says_so(self, mcp_client, db_manager, monkeypatch):
        """A log line nobody reads is the 'silent' half of the defect.

        The signal has to travel on the response, because the caller is an agent in
        someone else's process that will never see our server log.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 4)
        _target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))

            assert payload.get("truncated") is True, (
                f"the response must tell the caller its list was cut short; got truncated={payload.get('truncated')!r}"
            )
            note = payload.get("truncation")
            assert isinstance(note, dict), f"a truncated response must carry a truncation detail block, got {note!r}"
            assert note.get("ceiling") == 4, f"the detail must name the ceiling that cut the list, got {note!r}"
            assert note.get("rows_fetched") == 4, f"the detail must state how many rows survived, got {note!r}"
            assert "completions" in note.get("dropped", ""), (
                f"the detail must say WHAT was dropped on a completion-oriented read, got {note!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)

    async def test_an_untruncated_response_says_it_was_not_truncated(self, mcp_client, db_manager, monkeypatch):
        """The other direction, and a BOTH-SIDES GUARD on the signal.

        ``truncated`` is always present and False on a complete list rather than absent:
        an agent must be able to read the field, and absence is indistinguishable from an
        older server. The detail block appears only when there is something to detail.
        """
        client, tenant_key = mcp_client
        monkeypatch.setattr(ceiling_mod, "_MCP_LIST_PROJECT_CEILING", 50)
        _target_id, rows = _completion_dataset()
        await _seed(db_manager, tenant_key, rows)

        try:
            payload = _payload(await _list_projects(client, include_completed=True))

            assert payload["count"] == len(rows), f"all seeded rows should be present, got {payload['count']}"
            assert payload.get("truncated") is False, (
                f"a complete list must report truncated=False, got {payload.get('truncated')!r}"
            )
            assert "truncation" not in payload, (
                f"a complete list must carry no truncation detail block, got {payload.get('truncation')!r}"
            )
        finally:
            await purge_tenant_rows(db_manager, tenant_key)


class TestTheCeilingItself:
    # Async only to match this module's blanket ``pytest.mark.asyncio``; it awaits
    # nothing because the ceiling is a module constant.
    async def test_the_ceiling_clears_the_measured_floor(self):
        """The ceiling stays -- BE-6071 F6a put it there as real fan-out protection -- but honest.

        It is raised to a measured number with headroom over the test-install tenant's real
        row count, not to a number that merely clears today's total. This asserts the
        floor so the value cannot drift back down without the test that documents why.
        """
        assert ceiling_mod._MCP_LIST_PROJECT_CEILING >= MEASURED_CEILING_FLOOR, (
            f"the agent-facing ceiling is {ceiling_mod._MCP_LIST_PROJECT_CEILING}, below the "
            f"measured floor of {MEASURED_CEILING_FLOOR}"
        )
