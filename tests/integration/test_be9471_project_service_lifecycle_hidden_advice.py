# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.models.projects import TaxonomyType
from tests.integration.test_be9468_list_projects_read_layer import (
    _content_text,
    _list_projects,
    _payload,
    _row,
    mcp_client,  # noqa: F401 -- re-exported fixture, pytest discovers it by name
)


pytestmark = pytest.mark.asyncio


async def _seed_typed(db_manager, tenant_key: str, type_abbrev: str, rows: list[dict]) -> str:
    from giljo_mcp.models.products import Product

    product_id = str(uuid.uuid4())
    taxonomy_type_id = str(uuid.uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9471 Product {uuid.uuid4().hex[:6]}",
                description="BE-9471 -- the lifecycle-hidden advice reproduction.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            TaxonomyType(
                id=taxonomy_type_id,
                tenant_key=tenant_key,
                abbreviation=type_abbrev,
                label=type_abbrev,
                color="#123456",
            )
        )
        for index, row in enumerate(rows, start=1):
            from giljo_mcp.models.projects import Project

            session.add(
                Project(
                    id=row["id"],
                    tenant_key=tenant_key,
                    product_id=product_id,
                    project_type_id=taxonomy_type_id,
                    name=row["name"],
                    description=row.get("description", "Seeded for the BE-9471 reproduction."),
                    mission="Prove the empty list explains itself.",
                    status=row["status"],
                    staging_status="staging_complete",
                    series_number=index,
                    created_at=_iso(row["created"]),
                    completed_at=_iso(row["completed"]) if row.get("completed") else None,
                )
            )
        await session.commit()

    return product_id


def _iso(day: str):
    from datetime import datetime

    return datetime.fromisoformat(f"{day}T12:00:00+00:00")


async def _add_empty_type(db_manager, tenant_key: str, type_abbrev: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            TaxonomyType(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                abbreviation=type_abbrev,
                label=type_abbrev,
                color="#654321",
            )
        )
        await session.commit()




class TestFullHideGetsTheAdviceLine:
    async def test_ui_shape_six_completed_all_hidden(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        rows = [_row(f"UI project {n}", "completed", f"2026-0{n}-01", f"2026-0{n}-15") for n in range(1, 7)]
        await _seed_typed(db_manager, tenant_key, "UI", rows)
        try:
            result = await _list_projects(client, project_type="UI", mode="triage")
            assert not result.is_error, f"must not error: {_content_text(result)!r}"
            payload = _payload(result)

            assert payload["counts"]["by_type"].get("UI") == 6, payload["counts"]["by_type"]
            assert payload["counts"]["matched"] == 0
            assert payload["count"] == 0
            assert payload["projects"] == []

            assert payload.get("truncated") is False, "no real cut happened; truncated must stay false"
            assert "truncation" not in payload
            advice = payload["counts"].get("advice")
            assert advice is not None, "no advice was attached to the emptied response"
            assert "UI" in advice
            assert "6" in advice
            assert "include_completed" in advice
        finally:
            await _purge(db_manager, tenant_key)

    async def test_db_shape_two_completed_all_hidden(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        rows = [_row(f"DB project {n}", "completed", f"2026-0{n}-01", f"2026-0{n}-15") for n in range(1, 3)]
        await _seed_typed(db_manager, tenant_key, "DB", rows)
        try:
            result = await _list_projects(client, project_type="DB", mode="triage")
            payload = _payload(result)

            assert payload["counts"]["by_type"].get("DB") == 2
            assert payload["counts"]["matched"] == 0
            assert payload["projects"] == []

            assert payload.get("truncated") is False
            assert "truncation" not in payload
            advice = payload["counts"].get("advice")
            assert advice is not None
            assert "DB" in advice
            assert "2" in advice
            assert "include_completed" in advice
        finally:
            await _purge(db_manager, tenant_key)




class TestPartialHideGetsTheAdviceLine:
    async def test_doc_shape_ten_of_eleven_hidden(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        rows = [_row(f"DOC project {n}", "completed", f"2026-{n:02d}-01", f"2026-{n:02d}-15") for n in range(1, 11)]
        rows.append(_row("DOC project 11", "inactive", "2026-11-01"))
        await _seed_typed(db_manager, tenant_key, "DOC", rows)
        try:
            result = await _list_projects(client, project_type="DOC", mode="triage")
            payload = _payload(result)

            assert payload["counts"]["by_type"].get("DOC") == 11
            assert payload["counts"]["matched"] == 1
            assert payload["count"] == 1

            assert payload.get("truncated") is False
            assert "truncation" not in payload
            advice = payload["counts"].get("advice")
            assert advice is not None
            assert "DOC" in advice
            assert "11" in advice
            assert "include_completed" in advice
        finally:
            await _purge(db_manager, tenant_key)




class TestGenuinelyEmptyStaysGenuinelyEmpty:
    async def test_a_type_with_zero_projects_anywhere_gets_no_advice(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        rows = [_row("Seed project", "active", "2026-01-01")]
        await _seed_typed(db_manager, tenant_key, "BE", rows)
        await _add_empty_type(db_manager, tenant_key, "API")
        try:
            result = await _list_projects(client, project_type="API", mode="triage")
            assert not result.is_error, f"must not error: {_content_text(result)!r}"
            payload = _payload(result)

            assert payload["counts"]["by_type"].get("API", 0) == 0
            assert payload["counts"]["matched"] == 0
            assert payload["projects"] == []
            assert payload.get("truncated") is False, "a genuinely-empty type must carry no advice"
            assert "truncation" not in payload
            assert "advice" not in payload["counts"]
        finally:
            await _purge(db_manager, tenant_key)

    async def test_explicit_status_is_not_a_hidden_default_and_gets_no_advice(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        rows = [_row(f"UI project {n}", "completed", f"2026-0{n}-01", f"2026-0{n}-15") for n in range(1, 7)]
        rows.append(_row("UI project active", "active", "2026-07-01"))
        await _seed_typed(db_manager, tenant_key, "UI", rows)
        try:
            result = await _list_projects(client, project_type="UI", status="active", mode="triage")
            payload = _payload(result)

            assert payload["counts"]["by_type"].get("UI") == 7
            assert payload["counts"]["matched"] == 1
            assert payload.get("truncated") is False, "an explicit status filter is not a hidden-default trap"
            assert "truncation" not in payload
            assert "advice" not in payload["counts"]
        finally:
            await _purge(db_manager, tenant_key)




class TestLifecycleAdviceNeverTouchesTruncation:
    async def test_no_real_cut_means_truncated_stays_false_even_with_advice(self, mcp_client, db_manager):  # noqa: F811
        client, tenant_key = mcp_client
        rows = [_row(f"UI project {n}", "completed", f"2026-0{n}-01", f"2026-0{n}-15") for n in range(1, 7)]
        await _seed_typed(db_manager, tenant_key, "UI", rows)
        try:
            result = await _list_projects(client, project_type="UI", mode="triage")
            payload = _payload(result)

            assert payload["counts"].get("advice") is not None, "precondition: advice must fire"
            assert payload["truncated"] is False
            assert "truncation" not in payload
        finally:
            await _purge(db_manager, tenant_key)

    async def test_a_real_limit_cut_alongside_lifecycle_advice_still_carries_a_real_cursor(
        self,
        mcp_client,  # noqa: F811
        db_manager,
    ):
        client, tenant_key = mcp_client
        rows = [_row(f"FE inactive {n}", "inactive", f"2026-{n:02d}-01") for n in range(1, 9)]
        rows += [_row(f"FE completed {n}", "completed", f"2026-{n:02d}-01", f"2026-{n:02d}-15") for n in range(1, 4)]
        await _seed_typed(db_manager, tenant_key, "FE", rows)
        try:
            result = await _list_projects(client, project_type="FE", limit=5, mode="triage")
            payload = _payload(result)

            assert payload["counts"]["by_type"].get("FE") == 11
            assert payload["counts"]["matched"] == 8
            assert payload["count"] == 5

            assert payload["truncated"] is True
            truncation = payload["truncation"]
            assert truncation["reason"] == "limit"
            assert truncation.get("next_cursor"), "a truncated:true response must carry a real next_cursor"

            advice = payload["counts"].get("advice")
            assert advice is not None
            assert "FE" in advice
            assert "8" in advice
            assert "11" in advice
        finally:
            await _purge(db_manager, tenant_key)


async def _purge(db_manager, tenant_key: str) -> None:
    from sqlalchemy import delete

    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project, TaxonomyType

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()
