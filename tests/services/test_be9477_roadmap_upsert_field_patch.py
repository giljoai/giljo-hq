# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9477 -- ``patch_fields`` at the layer the defect lives in, against a real Postgres.

The agent-visible failure is pinned at the MCP boundary in
``tests/integration/test_be9477_roadmap_field_patch_mcp_transport.py``. This file
covers the two things that are impractical to state there:

- **the back-compat matrix** -- flag off vs on, x each metadata column, x insert vs
  update, x omitted vs explicitly-empty. Parametrized rather than prose, because the
  whole decision is that omitted and explicitly-empty are DIFFERENT instructions and
  the only way to show that is to run both against every column.
- **BE-9144's batching, still intact.** ``roadmap_upsert.upsert_many`` is one multi-row
  ``INSERT ... ON CONFLICT``, collapsed from a per-item loop for performance, and
  patch mode groups rows by which columns they carry. These assert that the collapse
  survives: flag off is one statement no matter what, and a uniform patch batch --
  what any re-rank sends -- is also one.

Museum rule: BE-9144's own guard (``test_be9144_roadmap_batch.py``) is untouched and
still green. Nothing here changes observable behaviour with the flag off.

Edition Scope: Both. Real DB via the transactional db_session; parallel-safe.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.roadmaps import RoadmapItem
from giljo_mcp.services.roadmap_service import RoadmapService
from giljo_mcp.services.roadmap_upsert import updated_columns
from giljo_mcp.services.roadmap_validation import (
    PATCH_FIELDS_KEY,
    PATCHABLE_ITEM_FIELDS,
    validate_items,
)
from giljo_mcp.tenant import TenantManager
from tests.helpers.taxonomy_seeds import next_series_number


# No module-level ``pytest.mark.asyncio``: this file mixes async DB tests with four
# pure-function ones, and a blanket mark warns on every sync test it touches. The
# suite already runs ``--asyncio-mode=auto`` (pyproject.toml addopts), so the async
# tests below are collected without it.


# Every metadata column set away from its default, so a clobber of any one shows.
_FULL_METADATA = {
    "sort_order": 3,
    "risk": "high",
    "complexity": "heavy",
    "blocked": True,
    "blocked_reason": "waiting on the migration",
}

# What each column reads as once cleared / defaulted.
_EMPTIED = {
    "sort_order": 0,
    "risk": None,
    "complexity": None,
    "blocked": False,
    "blocked_reason": None,
}

# How a caller says "clear this one" per column. ``sort_order`` is NOT NULL with a
# numeric default, so its empty value is 0 -- null stays a validation error there,
# unchanged by this project (pinned below).
_EXPLICIT_EMPTY = {
    "sort_order": 0,
    "risk": None,
    "complexity": "",
    "blocked": False,
    "blocked_reason": None,
}


class _StatementCounter:
    """Count cursor executions, split by a substring of interest.

    Verbatim in shape from ``test_be9144_roadmap_batch.py`` so the batching claims
    here are measured the same way BE-9144's own guard measures them.
    """

    def __init__(self, engine):
        self._engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def count(self, needle: str) -> int:
        upper = needle.upper()
        return sum(1 for s in self.statements if upper in s.upper())


@pytest_asyncio.fixture
async def seeded(db_session, test_tenant_key):
    """Active product + 5 projects to reference from roadmap items."""
    product = Product(
        id=str(uuid4()),
        name=f"RM {uuid4().hex[:6]}",
        description="be9477 field patch",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    project_ids: list[str] = []
    for idx in range(5):
        project = Project(
            id=str(uuid4()),
            tenant_key=test_tenant_key,
            product_id=product.id,
            name=f"P{idx}",
            description="d",
            mission="m",
            series_number=next_series_number(),
            status="inactive",
        )
        db_session.add(project)
        project_ids.append(project.id)
    await db_session.flush()
    return {"product_id": product.id, "project_ids": project_ids}


def _service(db_session):
    return RoadmapService(tenant_manager=TenantManager(), session=db_session)


async def _row(db_session, project_id: str) -> RoadmapItem:
    return (await db_session.execute(select(RoadmapItem).where(RoadmapItem.project_id == project_id))).scalar_one()


async def _seed_full_row(svc, tenant_key: str, project_id: str) -> None:
    """Store one fully-populated row through the ordinary (flag off) path."""
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": project_id, **_FULL_METADATA}],
        tenant_key=tenant_key,
    )


# ---------------------------------------------------------------------------
# THE BACK-COMPAT MATRIX
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_update_flag_off_resets_every_omitted_column(db_session, test_tenant_key, seeded, column):
    """Flag OFF, UPDATE, column OMITTED -> reset. Today's behaviour, pinned per column.

    This is the defect BE-9477 exists for and it is deliberately still true with the
    flag unset: an already-staged release must not move under an existing caller.
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid, "sort_order": 9}],
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    expected = 9 if column == "sort_order" else _EMPTIED[column]
    assert getattr(row, column) == expected


@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_update_flag_on_keeps_every_omitted_column(db_session, test_tenant_key, seeded, column):
    """Flag ON, UPDATE, column OMITTED -> the stored value survives. The fix."""
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid, "sort_order": 9}],
        patch_fields=True,
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    expected = 9 if column == "sort_order" else _FULL_METADATA[column]
    assert getattr(row, column) == expected


@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_update_flag_on_clears_every_explicitly_empty_column(db_session, test_tenant_key, seeded, column):
    """Flag ON, UPDATE, column EXPLICITLY EMPTY -> cleared. Option A's other half.

    Paired with the test above this is the load-bearing distinction: the SAME column,
    the SAME flag, one omitted and one sent empty, landing differently. An
    implementation using ``coalesce(excluded.x, table.x)`` passes the omitted case and
    fails this one, which is why that shape is foreclosed rather than discouraged.
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    item = {"item_type": "project", "project_id": pid, column: _EXPLICIT_EMPTY[column]}
    if column in ("blocked", "blocked_reason"):
        # The pair is patched as a unit -- see test_patch_refuses_half_a_blocked_pair.
        item = {"item_type": "project", "project_id": pid, "blocked": False, "blocked_reason": None}

    await svc.upsert_metadata(items=[item], patch_fields=True, tenant_key=test_tenant_key)

    row = await _row(db_session, pid)
    assert getattr(row, column) == _EMPTIED[column]


@pytest.mark.parametrize("patch_fields", [False, True])
@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_insert_takes_column_defaults_under_either_flag(
    db_session, test_tenant_key, seeded, column, patch_fields
):
    """INSERT, column OMITTED, flag either way -> the ordinary default.

    Patch semantics apply to the UPDATE half only: a row that does not exist yet has
    no stored value to preserve. Both flag states must agree here, or "patch" would
    quietly mean something different for a first save than for a later edit.
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid}],
        patch_fields=patch_fields,
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    assert getattr(row, column) == _EMPTIED[column]


@pytest.mark.parametrize("patch_fields", [False, True])
@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_insert_stores_an_explicit_value_under_either_flag(
    db_session, test_tenant_key, seeded, column, patch_fields
):
    """INSERT with every field supplied -> identical under both flag states."""
    svc = _service(db_session)
    pid = seeded["project_ids"][0]

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid, **_FULL_METADATA}],
        patch_fields=patch_fields,
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    assert getattr(row, column) == _FULL_METADATA[column]


async def test_omitted_and_explicitly_empty_diverge_in_one_call(db_session, test_tenant_key, seeded):
    """Two identically-seeded rows, one omitting risk and one nulling it, same call.

    The matrix above proves each half separately; this proves they can disagree
    within a single statement group, which is where a naive implementation would
    collapse them back together.
    """
    svc = _service(db_session)
    keeper, clearer = seeded["project_ids"][0], seeded["project_ids"][1]
    for pid in (keeper, clearer):
        await _seed_full_row(svc, test_tenant_key, pid)

    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": keeper, "sort_order": 1},
            {"item_type": "project", "project_id": clearer, "sort_order": 2, "risk": None},
        ],
        patch_fields=True,
        tenant_key=test_tenant_key,
    )

    assert (await _row(db_session, keeper)).risk == "high"
    assert (await _row(db_session, clearer)).risk is None


# ---------------------------------------------------------------------------
# THE blocked / blocked_reason PAIR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("item_extra", "missing"),
    [
        ({"blocked_reason": "waiting on the auth gate"}, "blocked"),
        ({"blocked": True}, "blocked_reason"),
        ({"blocked": False}, "blocked_reason"),
    ],
)
async def test_patch_refuses_half_a_blocked_pair(db_session, test_tenant_key, seeded, item_extra, missing):
    """Half a pair is refused by name, and nothing is written.

    All three single-key cases are refused, INCLUDING ``{blocked: true}`` alone,
    which is genuinely harmless -- the parametrization pins that deliberately.
    The rule is over-broad on purpose: the other two are valid or invalid
    depending on the row's STORED state, so a permissive rule would accept or
    refuse the identical request based on data the caller cannot see. Predictable
    beats permissive here. Full reasoning:
    ``roadmap_validation._check_patch_pairing``.

    The refusal fires only under the flag, so no call that succeeds today is affected.
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    with pytest.raises(ValidationError) as exc:
        await svc.upsert_metadata(
            items=[{"item_type": "project", "project_id": pid, **item_extra}],
            patch_fields=True,
            tenant_key=test_tenant_key,
        )

    assert missing in str(exc.value)
    assert "patch_fields" in str(exc.value)
    row = await _row(db_session, pid)
    assert row.blocked is True and row.blocked_reason == "waiting on the migration"


@pytest.mark.parametrize("item_extra", [{"blocked_reason": "x"}, {"blocked": True}])
async def test_flag_off_still_accepts_half_a_blocked_pair(db_session, test_tenant_key, seeded, item_extra):
    """The pairing refusal is NEW SURFACE ONLY -- flag off, the same payload succeeds.

    Pre-ruling 4: no change whose effect is "a call that succeeds today now fails".
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]

    result = await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid, **item_extra}],
        tenant_key=test_tenant_key,
    )

    assert result["items_upserted"] == 1


async def test_patch_writes_the_whole_pair_when_both_are_sent(db_session, test_tenant_key, seeded):
    """Both halves present -> both written, with the unblocked-carries-no-note rule applied."""
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid, "blocked": False, "blocked_reason": "stale note"}],
        patch_fields=True,
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    assert row.blocked is False
    assert row.blocked_reason is None, "an unblocked item never keeps a note"
    assert row.risk == "high", "the untouched columns survived the pair write"


async def test_patch_leaves_sort_order_validation_alone(db_session, test_tenant_key, seeded):
    """``sort_order: null`` is still refused as a non-integer, flag on or off.

    ``sort_order`` is NOT NULL with a numeric default, so it has no null form to
    clear to -- its empty value is 0. Stated as a test rather than left implicit,
    because the tool's own description promises null clears a field and this is the
    one column where that is not true.
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]

    for patch_fields in (False, True):
        with pytest.raises(ValidationError) as exc:
            await svc.upsert_metadata(
                items=[{"item_type": "project", "project_id": pid, "sort_order": None}],
                patch_fields=patch_fields,
                tenant_key=test_tenant_key,
            )
        assert "must be an integer" in str(exc.value)


# ---------------------------------------------------------------------------
# BE-9144's BATCHING, STILL INTACT (museum rule)
# ---------------------------------------------------------------------------


async def test_flag_off_is_still_exactly_one_insert(db_session, db_manager, test_tenant_key, seeded):
    """Flag OFF, 5 rows of mixed shapes -> ONE INSERT. BE-9144's collapse, unmoved.

    Mixed shapes deliberately: with the flag off, shape is irrelevant because every
    row writes every column, so grouping must not kick in at all.
    """
    svc = _service(db_session)
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i, **dict(list(_FULL_METADATA.items())[: i % 4])}
        for i, pid in enumerate(seeded["project_ids"])
    ]

    with _StatementCounter(db_manager.async_engine.sync_engine) as counter:
        await svc.upsert_metadata(items=items, tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 1, counter.statements


async def test_patch_batch_of_one_shape_is_still_exactly_one_insert(db_session, db_manager, test_tenant_key, seeded):
    """Flag ON, 5 rows all carrying the SAME keys -> ONE INSERT.

    This is the shape a re-rank actually sends (every row carrying sort_order and
    nothing else), so the common patch-mode path costs exactly what BE-9144 made it
    cost -- the collapse is not traded away for the fix.
    """
    svc = _service(db_session)
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i} for i, pid in enumerate(seeded["project_ids"])
    ]

    with _StatementCounter(db_manager.async_engine.sync_engine) as counter:
        await svc.upsert_metadata(items=items, patch_fields=True, tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 1, counter.statements


async def test_patch_batch_issues_one_insert_per_distinct_shape(db_session, db_manager, test_tenant_key, seeded):
    """Flag ON, 4 rows in 2 shapes -> 2 INSERTs, and the cost is stated not hidden.

    A statement's SET clause is fixed for all its rows, so rows patching different
    columns cannot share one. The bound is the number of DISTINCT shapes, not the row
    count: 4 rows in 2 shapes cost 2, never 4. Pinned so a future change that silently
    reverted to per-row statements would be caught.
    """
    svc = _service(db_session)
    pids = seeded["project_ids"]
    items = [
        {"item_type": "project", "project_id": pids[0], "sort_order": 1},
        {"item_type": "project", "project_id": pids[1], "sort_order": 2},
        {"item_type": "project", "project_id": pids[2], "risk": "low"},
        {"item_type": "project", "project_id": pids[3], "risk": "med"},
    ]

    with _StatementCounter(db_manager.async_engine.sync_engine) as counter:
        await svc.upsert_metadata(items=items, patch_fields=True, tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 2, counter.statements


async def test_patch_keeps_last_write_wins_for_an_intra_call_duplicate(db_session, test_tenant_key, seeded):
    """Two items, same conflict key, patch mode -> the LAST one wins whole.

    BE-9144's de-dup contract, restated under the flag. The last item's shape decides
    the write; the earlier item does not merge into it. Changing that would be a
    behaviour change to the exhibit, which needs its own incident, not this project.
    """
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    await svc.upsert_metadata(
        items=[
            {"item_type": "project", "project_id": pid, "risk": None},
            {"item_type": "project", "project_id": pid, "sort_order": 8},
        ],
        patch_fields=True,
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    assert row.sort_order == 8
    assert row.risk == "high", "the earlier duplicate's clear did not apply -- last write wins whole"


async def test_patching_nothing_keeps_everything(db_session, test_tenant_key, seeded):
    """An item carrying no metadata at all leaves every stored value alone."""
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid}],
        patch_fields=True,
        tenant_key=test_tenant_key,
    )

    row = await _row(db_session, pid)
    for column, value in _FULL_METADATA.items():
        assert getattr(row, column) == value


# ---------------------------------------------------------------------------
# THE PIECES THE ABOVE RESTS ON
# ---------------------------------------------------------------------------


def test_validated_item_is_byte_identical_with_the_flag_off():
    """Flag off, the normalized row carries no patch bookkeeping at all.

    ``_patch_fields`` cannot be added unconditionally: the normalized dict is asserted
    by whole-dict equality in ``test_roadmap_validation.py``, and more importantly an
    always-on key would change what every existing caller sees for no reason.
    """
    (row,) = validate_items([{"item_type": "project", "project_id": "p1", "risk": "low"}])
    assert PATCH_FIELDS_KEY not in row


def test_validated_item_records_only_the_keys_actually_supplied():
    """Flag on, presence is literal: sent-as-empty counts, absent does not."""
    (row,) = validate_items(
        [{"item_type": "project", "project_id": "p1", "sort_order": 2, "risk": None}],
        patch_fields=True,
    )
    assert row[PATCH_FIELDS_KEY] == frozenset({"sort_order", "risk"})


def test_updated_columns_is_the_full_canonical_list_when_the_flag_is_off():
    """Flag off emits the same SET clause, in the same order, as before BE-9477.

    Order is asserted, not just membership: the pre-BE-9477 statement wrote
    sort_order, risk, complexity, blocked, blocked_reason in that sequence, and
    matching it means the emitted SQL is unchanged rather than merely equivalent.
    """
    assert updated_columns({}, patch_fields=False) == (
        "sort_order",
        "risk",
        "complexity",
        "blocked",
        "blocked_reason",
    )


def test_updated_columns_is_canonical_order_regardless_of_how_the_agent_wrote_it():
    """Two payloads supplying the same keys must group together whatever the key order.

    Without canonical ordering they would hash to different signatures and split into
    two statements that do exactly the same thing.
    """
    supplied = frozenset({"blocked_reason", "risk", "blocked"})
    assert updated_columns({PATCH_FIELDS_KEY: supplied}, patch_fields=True) == (
        "risk",
        "blocked",
        "blocked_reason",
    )
