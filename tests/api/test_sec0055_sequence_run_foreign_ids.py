# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from giljo_mcp.models import Project
from tests.api.test_sequence_run_endpoints_product_scope import _seed_tenant


pytestmark = pytest.mark.asyncio

RUNS = "/api/v1/sequence-runs"


async def _two_own_projects(db_manager, seeded: dict) -> list[str]:
    async with db_manager.get_session_async(tenant_key=seeded["tenant_key"]) as session:
        extra = Project(
            id=str(uuid.uuid4()),
            tenant_key=seeded["tenant_key"],
            product_id=seeded["product_id"],
            name="second member",
            series_number=2,
            description="desc",
            mission="mission",
        )
        session.add(extra)
        await session.commit()
    return [seeded["project_id"], extra.id]


async def _runs_naming(db_manager, project_id: str) -> int:
    async with db_manager.get_session_async() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM sequence_runs WHERE project_ids::text LIKE :p "
                "OR resolved_order::text LIKE :p OR conductor_project_id = :pid"
            ),
            {"p": f"%{project_id}%", "pid": project_id},
        )


async def _create(api_client, headers: dict, ids: list[str]):
    return await api_client.post(
        RUNS,
        headers=headers,
        json={"project_ids": ids, "resolved_order": ids, "execution_mode": "multi_terminal"},
    )


async def test_create_with_a_foreign_project_id_is_refused(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    foreign = await _seed_tenant(db_manager)

    resp = await _create(api_client, own["headers"], [own["project_id"], foreign["project_id"]])

    assert resp.status_code == 404, resp.text
    assert await _runs_naming(db_manager, foreign["project_id"]) == 0


async def test_create_with_own_project_ids_still_works(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    ids = await _two_own_projects(db_manager, own)

    resp = await _create(api_client, own["headers"], ids)

    assert resp.status_code == 201, resp.text
    assert resp.json()["project_ids"] == ids


async def test_update_to_a_foreign_conductor_project_id_is_refused(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    foreign = await _seed_tenant(db_manager)
    created = await _create(api_client, own["headers"], await _two_own_projects(db_manager, own))
    assert created.status_code == 201, created.text

    resp = await api_client.patch(
        f"{RUNS}/{created.json()['id']}",
        headers=own["headers"],
        json={"conductor_project_id": foreign["project_id"]},
    )

    assert resp.status_code == 404, resp.text
    assert await _runs_naming(db_manager, foreign["project_id"]) == 0


async def test_update_to_a_foreign_resolved_order_is_refused(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    foreign = await _seed_tenant(db_manager)
    ids = await _two_own_projects(db_manager, own)
    created = await _create(api_client, own["headers"], ids)
    assert created.status_code == 201, created.text

    resp = await api_client.patch(
        f"{RUNS}/{created.json()['id']}",
        headers=own["headers"],
        json={"resolved_order": [ids[0], foreign["project_id"]]},
    )

    assert resp.status_code == 404, resp.text
    assert await _runs_naming(db_manager, foreign["project_id"]) == 0


async def test_update_to_an_own_conductor_project_id_still_works(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    ids = await _two_own_projects(db_manager, own)
    created = await _create(api_client, own["headers"], ids)
    assert created.status_code == 201, created.text

    resp = await api_client.patch(
        f"{RUNS}/{created.json()['id']}",
        headers=own["headers"],
        json={"conductor_project_id": ids[0], "resolved_order": list(reversed(ids))},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["conductor_project_id"] == ids[0]


async def _runs_with_status_key(db_manager, project_id: str) -> int:
    async with db_manager.get_session_async() as session:
        return await session.scalar(
            text("SELECT count(*) FROM sequence_runs WHERE project_statuses ? :pid"), {"pid": project_id}
        )


async def test_create_with_a_foreign_project_statuses_key_is_refused(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    foreign = await _seed_tenant(db_manager)
    ids = await _two_own_projects(db_manager, own)

    resp = await api_client.post(
        RUNS,
        headers=own["headers"],
        json={
            "project_ids": ids,
            "resolved_order": ids,
            "execution_mode": "multi_terminal",
            "project_statuses": {foreign["project_id"]: "planning"},
        },
    )

    assert resp.status_code == 404, resp.text
    assert await _runs_with_status_key(db_manager, foreign["project_id"]) == 0


async def test_update_to_a_foreign_project_statuses_key_is_refused(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    foreign = await _seed_tenant(db_manager)
    created = await _create(api_client, own["headers"], await _two_own_projects(db_manager, own))
    assert created.status_code == 201, created.text

    resp = await api_client.patch(
        f"{RUNS}/{created.json()['id']}",
        headers=own["headers"],
        json={"project_statuses": {foreign["project_id"]: "planning"}},
    )

    assert resp.status_code == 404, resp.text
    assert await _runs_with_status_key(db_manager, foreign["project_id"]) == 0


async def test_update_to_own_project_statuses_still_works(api_client, db_manager):
    own = await _seed_tenant(db_manager)
    ids = await _two_own_projects(db_manager, own)
    created = await _create(api_client, own["headers"], ids)
    assert created.status_code == 201, created.text

    resp = await api_client.patch(
        f"{RUNS}/{created.json()['id']}", headers=own["headers"], json={"project_statuses": {ids[0]: "planning"}}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["project_statuses"] == {ids[0]: "planning"}
