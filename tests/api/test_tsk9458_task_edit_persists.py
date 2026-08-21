# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9458 regression — editing a task's text through the dashboard persists.

The operator's report
=====================
    "when the user writes a task, then goes back to update it,
     it wont save the updated text"

The mechanism
=============
Every task is forced onto the reserved ``TSK`` tag (BE-6049c), and
``task_to_response`` echoes that tag back to the client as ``task_type="TSK"``.
The edit dialog seeds its form from the fetched task (``{ ...task }``) and sends
the whole object back, so the round-tripped ``task_type="TSK"`` is present in
the ``PUT``/``PATCH`` body and is therefore "set" for ``exclude_unset``.

``PATCH /tasks/{id}`` then re-resolved any inbound ``task_type`` through
``TaxonomyService.validate()``, which *rejects* ``TSK`` because it is a reserved
runtime-only tag — so the request raised before ``update_task()`` was ever
called and the user's new title/description were dropped on the floor.

The user never asked to change the type. They echoed back the value the API had
just handed them, and the write died on it.

Tests live at the REST boundary (``api_client``) because that is the layer the
defect lived at: the service-layer allowlist already permits ``title`` and
``description``, and a service-layer test passes on both sides of this fix.
"""

from __future__ import annotations

import secrets
import uuid

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.models import Product, Task, User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.tenant import TenantManager


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_user_with_product(db_manager) -> dict:
    """Create org + user + ACTIVE product in a fresh tenant; return auth + ids."""
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="Test product",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(product)
        await session.commit()

        token = JWTManager.create_access_token(
            user_id=user.id,
            username=user.username,
            role="developer",
            tenant_key=tenant_key,
        )
        return {
            "tenant_key": tenant_key,
            "user_id": user.id,
            "product_id": product.id,
            "headers": {
                "Cookie": f"access_token={token}; csrf_token={_TEST_CSRF_TOKEN}",
                "X-CSRF-Token": _TEST_CSRF_TOKEN,
            },
        }


@pytest_asyncio.fixture(scope="function")
async def seeded_product(db_manager):
    return await _seed_user_with_product(db_manager)


async def _create_task(api_client: AsyncClient, seeded: dict) -> dict:
    """Create a task the way the dashboard's New Task button does."""
    resp = await api_client.post(
        "/api/v1/tasks/",
        headers=seeded["headers"],
        json={
            "title": "original title",
            "description": "original description",
            "product_id": seeded["product_id"],
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _read_back(db_manager, task_id: str, tenant_key: str) -> Task | None:
    # Out-of-request read: thread tenant explicitly for the fail-closed guard
    # (BE-6004), mirroring the sibling completion-notes regression suite.
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        return await session.get(Task, task_id)


@pytest.mark.asyncio
async def test_round_tripped_task_type_does_not_discard_the_edit(
    api_client: AsyncClient, db_manager, seeded_product: dict
) -> None:
    """The exact TSK-9458 repro: edit the text on a body echoed back from the API.

    This is the dashboard's real payload shape -- the dialog spreads the fetched
    task and PUTs it back, so ``task_type="TSK"`` rides along untouched.
    """
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]

    # The API hands the client TSK; the client will hand it straight back.
    assert created["task_type"] == "TSK", created

    fetched = await api_client.get(f"/api/v1/tasks/{task_id}/", headers=seeded_product["headers"])
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["task_type"] == "TSK", body

    # What the edit dialog sends: the whole fetched object, text changed.
    payload = {
        "title": "EDITED title",
        "description": "EDITED description",
        "status": body["status"],
        "priority": body["priority"],
        "task_type": body["task_type"],  # <-- echoed back, never chosen by the user
    }
    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json=payload,
    )
    assert resp.status_code == 200, resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert row.title == "EDITED title", "the user's edited title was discarded"
    assert row.description == "EDITED description", "the user's edited description was discarded"


@pytest.mark.asyncio
async def test_edit_without_task_type_still_persists(api_client: AsyncClient, db_manager, seeded_product: dict) -> None:
    """Control: with no ``task_type`` in the body the edit always saved.

    This passes on BOTH sides of the fix. It is here to prove the repro above
    isolates the round-tripped tag and is not a broken harness -- if this one
    ever goes red, suspect the instrument, not the fix.
    """
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json={"title": "no-type title", "description": "no-type description"},
    )
    assert resp.status_code == 200, resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert row.title == "no-type title"
    assert row.description == "no-type description"


@pytest.mark.asyncio
async def test_reserved_tag_stays_bound_after_an_edit(
    api_client: AsyncClient, db_manager, seeded_product: dict
) -> None:
    """Accepting the echoed TSK must not rebind or clear the task's type.

    ``task_type_id`` is immutable by design (BE-6049c). Tolerating the echo is
    a no-op, never a write -- the task is still TSK afterwards.
    """
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]
    original_type_id = created["task_type_id"]
    assert original_type_id is not None, created

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json={"title": "still TSK", "task_type": "TSK"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["task_type"] == "TSK", resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert str(row.task_type_id) == str(original_type_id), "the reserved tag was rebound by an edit"


@pytest.mark.asyncio
async def test_a_genuinely_unknown_task_type_is_still_rejected(
    api_client: AsyncClient, db_manager, seeded_product: dict
) -> None:
    """Tolerating the reserved echo must not open the gate to bogus types.

    A caller sending a type that does not exist still gets a 4xx -- the fix is
    scoped to the reserved tag the API itself emitted, nothing wider.
    """
    created = await _create_task(api_client, seeded_product)
    task_id = created["id"]

    resp = await api_client.put(
        f"/api/v1/tasks/{task_id}/",
        headers=seeded_product["headers"],
        json={"title": "bogus type", "task_type": "ZZZZ"},
    )
    assert 400 <= resp.status_code < 500, resp.text

    row = await _read_back(db_manager, task_id, seeded_product["tenant_key"])
    assert row is not None
    assert row.title == "original title", "a rejected update must not partially apply"
