# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




_FULL_METADATA = {
    "sort_order": 3,
    "risk": "high",
    "complexity": "heavy",
    "blocked": True,
    "blocked_reason": "waiting on the migration",
}

_EMPTIED = {
    "sort_order": 0,
    "risk": None,
    "complexity": None,
    "blocked": False,
    "blocked_reason": None,
}

_EXPLICIT_EMPTY = {
    "sort_order": 0,
    "risk": None,
    "complexity": "",
    "blocked": False,
    "blocked_reason": None,
}


class _StatementCounter:

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
    await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": project_id, **_FULL_METADATA}],
        tenant_key=tenant_key,
    )




@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_update_flag_off_resets_every_omitted_column(db_session, test_tenant_key, seeded, column):
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
    svc = _service(db_session)
    pid = seeded["project_ids"][0]
    await _seed_full_row(svc, test_tenant_key, pid)

    item = {"item_type": "project", "project_id": pid, column: _EXPLICIT_EMPTY[column]}
    if column in ("blocked", "blocked_reason"):
        item = {"item_type": "project", "project_id": pid, "blocked": False, "blocked_reason": None}

    await svc.upsert_metadata(items=[item], patch_fields=True, tenant_key=test_tenant_key)

    row = await _row(db_session, pid)
    assert getattr(row, column) == _EMPTIED[column]


@pytest.mark.parametrize("patch_fields", [False, True])
@pytest.mark.parametrize("column", PATCHABLE_ITEM_FIELDS)
async def test_insert_takes_column_defaults_under_either_flag(
    db_session, test_tenant_key, seeded, column, patch_fields
):
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




@pytest.mark.parametrize(
    ("item_extra", "missing"),
    [
        ({"blocked_reason": "waiting on the auth gate"}, "blocked"),
        ({"blocked": True}, "blocked_reason"),
        ({"blocked": False}, "blocked_reason"),
    ],
)
async def test_patch_refuses_half_a_blocked_pair(db_session, test_tenant_key, seeded, item_extra, missing):
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
    svc = _service(db_session)
    pid = seeded["project_ids"][0]

    result = await svc.upsert_metadata(
        items=[{"item_type": "project", "project_id": pid, **item_extra}],
        tenant_key=test_tenant_key,
    )

    assert result["items_upserted"] == 1


async def test_patch_writes_the_whole_pair_when_both_are_sent(db_session, test_tenant_key, seeded):
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




async def test_flag_off_is_still_exactly_one_insert(db_session, db_manager, test_tenant_key, seeded):
    svc = _service(db_session)
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i, **dict(list(_FULL_METADATA.items())[: i % 4])}
        for i, pid in enumerate(seeded["project_ids"])
    ]

    with _StatementCounter(db_manager.async_engine.sync_engine) as counter:
        await svc.upsert_metadata(items=items, tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 1, counter.statements


async def test_patch_batch_of_one_shape_is_still_exactly_one_insert(db_session, db_manager, test_tenant_key, seeded):
    svc = _service(db_session)
    items = [
        {"item_type": "project", "project_id": pid, "sort_order": i} for i, pid in enumerate(seeded["project_ids"])
    ]

    with _StatementCounter(db_manager.async_engine.sync_engine) as counter:
        await svc.upsert_metadata(items=items, patch_fields=True, tenant_key=test_tenant_key)

    assert counter.count("INSERT INTO roadmap_items") == 1, counter.statements


async def test_patch_batch_issues_one_insert_per_distinct_shape(db_session, db_manager, test_tenant_key, seeded):
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




def test_validated_item_is_byte_identical_with_the_flag_off():
    (row,) = validate_items([{"item_type": "project", "project_id": "p1", "risk": "low"}])
    assert PATCH_FIELDS_KEY not in row


def test_validated_item_records_only_the_keys_actually_supplied():
    (row,) = validate_items(
        [{"item_type": "project", "project_id": "p1", "sort_order": 2, "risk": None}],
        patch_fields=True,
    )
    assert row[PATCH_FIELDS_KEY] == frozenset({"sort_order", "risk"})


def test_updated_columns_is_the_full_canonical_list_when_the_flag_is_off():
    assert updated_columns({}, patch_fields=False) == (
        "sort_order",
        "risk",
        "complexity",
        "blocked",
        "blocked_reason",
    )


def test_updated_columns_is_canonical_order_regardless_of_how_the_agent_wrote_it():
    supplied = frozenset({"blocked_reason", "risk", "blocked"})
    assert updated_columns({PATCH_FIELDS_KEY: supplied}, patch_fields=True) == (
        "risk",
        "blocked",
        "blocked_reason",
    )
