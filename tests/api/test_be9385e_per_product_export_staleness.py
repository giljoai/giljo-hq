# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9385e -- the "last exported" indicator must tell the truth about THIS product.

THE LIE. ``last_exported_at`` lives on ``agent_templates``, which is tenant-wide.
Exporting the agents for product A stamps that shared column, and product B --
which has never been exported in its life -- then reads the same row and renders
"exported just now". The indicator is not merely imprecise; it reports another
product's action as this product's state, and the user's only defence against
shipping stale agents is that indicator.

WHY A VALUE-KEYED FALLBACK CANNOT FIX IT. Reading "junction value, else template
value" fixes nothing, because the template value is not absent -- it is *someone
else's truth*. Product A's export sets it, and B's NULL junction then falls back
onto exactly the wrong number. This was not reasoned, it was measured: with the
per-product column, the migration and the writer all in place, the first test
below was STILL red under a value-keyed read.

The tenant-wide column cannot simply stop being written either -- BE-9208's
staged-ZIP freshness guard reads ``MAX(agent_templates.last_exported_at)``
(``file_staging.py:99``), so freezing it regresses that. So tolerance is keyed on
ROW EXISTENCE, the same predicate ``product_agent_selection`` uses for selection:
a row that exists answers (NULL = "this product has not exported it"), and only a
MISSING row falls back to the tenant-wide value.

Layer: the authenticated HTTP boundary, per the house bug-fix rule. The badge is
rendered from ``GET /api/v1/templates/``'s ``last_exported_at`` / ``may_be_stale``
fields, and the export that pollutes them is ``GET /api/download/agent-templates.zip``
-- so both halves are driven through the real endpoints rather than a service,
because a service-level test would not have caught a response converter that
ignores the product.

Parallel-safe: unique tenant per test (from the JWT), uniquely-named rows, no
module-level mutable state, no ordering dependency.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate


def _extract_tenant_key(auth_headers: dict) -> str:
    """Decode the tenant_key baked into the JWT access_token cookie."""
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


async def _seed_two_products_sharing_one_agent(db_manager, tenant_key: str, suffix: str) -> dict:
    """One agent, two curated products, product A active.

    Both products carry a junction row for the agent -- the post-``ce_0091``
    world, where every product is curated and selection is authoritative.
    """
    agent_id = str(uuid4())
    product_a_id = str(uuid4())
    product_b_id = str(uuid4())
    agent_name = f"be9385e-shared-{suffix}"

    async with db_manager.get_session_async() as session:
        session.add(
            AgentTemplate(
                id=agent_id,
                tenant_key=tenant_key,
                name=agent_name,
                role="custom",
                category="custom",
                system_instructions="sys",
                user_instructions="body",
                tool="claude",
                cli_tool="claude",
                is_active=True,
                version="1.0.0",
            )
        )
        session.add(Product(id=product_a_id, tenant_key=tenant_key, name=f"BE9385e A {suffix}", is_active=True))
        session.add(Product(id=product_b_id, tenant_key=tenant_key, name=f"BE9385e B {suffix}", is_active=False))
        await session.flush()

        for product_id in (product_a_id, product_b_id):
            session.add(
                ProductAgentAssignment(
                    id=str(uuid4()),
                    product_id=product_id,
                    template_id=agent_id,
                    tenant_key=tenant_key,
                    is_active=True,
                )
            )
        await session.commit()

    return {"agent_id": agent_id, "agent_name": agent_name, "product_a": product_a_id, "product_b": product_b_id}


async def _switch_active_product(db_manager, tenant_key: str, *, on: str, off: str) -> None:
    """Make ``on`` the tenant's active product and ``off`` dormant.

    ``off`` is cleared first: ``idx_product_single_active_per_tenant`` permits
    exactly one active product per tenant, so the other order would collide.
    """
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(
                update(Product).where(Product.id == off, Product.tenant_key == tenant_key).values(is_active=False)
            )
            await session.execute(
                update(Product).where(Product.id == on, Product.tenant_key == tenant_key).values(is_active=True)
            )
        await session.commit()


async def _read_agent(api_client, auth_headers: dict, agent_name: str) -> dict:
    """The agent as the Agents screen sees it, through the real list endpoint."""
    resp = await api_client.get("/api/v1/templates/", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    rows = [row for row in resp.json() if row["name"] == agent_name]
    assert rows, f"{agent_name} missing from the template list."
    return rows[0]


@pytest.mark.asyncio
async def test_exporting_one_product_does_not_mark_another_product_as_freshly_exported(
    api_client, auth_headers, db_manager
):
    """THE LIE, at the surface the user reads it from. Fail-first against master.

    Pre-fix, product B reports a ``last_exported_at`` it never earned and
    ``may_be_stale`` False -- product A's export, displayed as B's state.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    suffix = uuid4().hex[:8]
    seeded = await _seed_two_products_sharing_one_agent(db_manager, tenant_key, suffix)

    # Product A is active: the user exports ITS agents.
    export = await api_client.get("/api/download/agent-templates.zip", headers=auth_headers)
    assert export.status_code == 200, export.text

    # The user switches to product B, which has never been exported.
    await _switch_active_product(db_manager, tenant_key, on=seeded["product_b"], off=seeded["product_a"])

    agent = await _read_agent(api_client, auth_headers, seeded["agent_name"])

    assert agent["last_exported_at"] is None, (
        "Product B reports an export it never had. The agents for product A were "
        f"exported and B now displays {agent['last_exported_at']!r} as its own "
        "last-exported time -- the tenant-wide column read as if it were per-product."
    )
    assert agent["may_be_stale"] is True, (
        "Product B's agent is shown as up to date because a DIFFERENT product was "
        "exported. The user's only warning that this product is shipping stale "
        "agents is this flag, and it is reporting someone else's export."
    )


@pytest.mark.asyncio
async def test_the_exporting_product_still_shows_its_own_export(api_client, auth_headers, db_manager):
    """The load-bearing other half: the fix must not blind the product that DID export.

    A per-product column that never reads back would 'fix' the lie by making the
    indicator useless everywhere, which is the failure mode worth guarding.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    suffix = uuid4().hex[:8]
    seeded = await _seed_two_products_sharing_one_agent(db_manager, tenant_key, suffix)

    export = await api_client.get("/api/download/agent-templates.zip", headers=auth_headers)
    assert export.status_code == 200, export.text

    # Still on product A -- the product that actually exported.
    agent = await _read_agent(api_client, auth_headers, seeded["agent_name"])

    assert agent["last_exported_at"] is not None, (
        "The product that just exported does not show its own export time. The "
        "per-product record was not written for the exporting product."
    )
    assert agent["may_be_stale"] is False, "The agent reads as stale immediately after this product exported it."


@pytest.mark.asyncio
async def test_a_product_with_no_junction_row_falls_back_to_the_tenant_wide_record(
    api_client, auth_headers, db_manager
):
    """TOLERANCE, keyed on ROW EXISTENCE -- the same predicate BE-9385a used.

    An UNCURATED product (no junction row for this agent) has no opinion, so the
    pre-existing tenant-wide record is shown rather than claiming the agent was
    never exported. This is why the tenant-wide column stays, and it is the
    upgrade path for installs whose products never got rows.

    Deliberately NOT "a row exists but is NULL": that case is answered, not
    absent, and is pinned by
    ``test_exporting_one_product_does_not_mark_another_product_as_freshly_exported``
    above. Falling back there would re-create the very defect this file is about
    -- the tenant-wide column is still written by every export (BE-9208's
    staged-ZIP watermark reads ``MAX(last_exported_at)``), so it always carries
    SOME product's export, and handing it to a product that never exported is the
    lie itself.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    suffix = uuid4().hex[:8]
    agent_id = str(uuid4())
    agent_name = f"be9385e-uncurated-{suffix}"

    # Pre-existing tenant-wide information, deterministically newer than the
    # template's own updated_at so staleness turns on the export, not the clock.
    exported_at = datetime.now(UTC) + timedelta(minutes=5)

    async with db_manager.get_session_async() as session:
        session.add(
            AgentTemplate(
                id=agent_id,
                tenant_key=tenant_key,
                name=agent_name,
                role="custom",
                category="custom",
                system_instructions="sys",
                user_instructions="body",
                tool="claude",
                cli_tool="claude",
                is_active=True,
                version="1.0.0",
                last_exported_at=exported_at,
            )
        )
        # An ACTIVE product that was never curated: no junction rows at all.
        session.add(Product(id=str(uuid4()), tenant_key=tenant_key, name=f"BE9385e Uncurated {suffix}", is_active=True))
        await session.commit()

    agent = await _read_agent(api_client, auth_headers, agent_name)

    assert agent["last_exported_at"] is not None, (
        "An uncurated product discarded the tenant-wide record instead of falling "
        "back to it. Pre-existing information was thrown away, and an agent that "
        "HAS been exported now claims it never was."
    )
    assert agent["may_be_stale"] is False, "The fallback value was read but not applied to the staleness rule."


@pytest.mark.asyncio
async def test_the_update_event_broadcasts_the_product_aware_staleness(
    api_client, auth_headers, db_manager, monkeypatch
):
    """The SEAM: the WebSocket event must agree with the response beside it.

    ``PUT /api/v1/templates/{id}`` returns a product-aware response AND publishes
    a ``template:updated`` event that the UI uses to refresh the row's staleness
    badge. The event originally carried ``template.may_be_stale`` -- the
    tenant-wide property -- so editing an agent flipped its badge straight back to
    another product's export: this project's defect, reintroduced at the one seam
    where both answers sit side by side.

    Nothing covered that payload's VALUE, so all of this file's other tests were
    green while the seam was broken. It was found by auditing consumers of the
    staleness rule; this test is what stops it coming back.

    The update is metadata-only (``is_active``) on purpose. That path deliberately
    preserves ``updated_at`` (so a toggle does not fake staleness), which is what
    makes the two readings DISAGREE here and the test meaningful:
      * tenant-wide -> created_at < product A's export -> False
      * product-aware -> product B's row exists but is NULL -> never exported here -> True
    A content edit would bump ``updated_at`` and read True under both, proving nothing.
    """
    from api import app_state

    tenant_key = _extract_tenant_key(auth_headers)
    suffix = uuid4().hex[:8]
    seeded = await _seed_two_products_sharing_one_agent(db_manager, tenant_key, suffix)

    # Product A exports, stamping the shared tenant-wide column.
    export = await api_client.get("/api/download/agent-templates.zip", headers=auth_headers)
    assert export.status_code == 200, export.text

    # The user switches to product B, which has never exported.
    await _switch_active_product(db_manager, tenant_key, on=seeded["product_b"], off=seeded["product_a"])

    published: list[tuple[str, dict]] = []

    class _CapturingBus:
        async def publish(self, event_name, payload):
            published.append((event_name, payload))

    monkeypatch.setattr(app_state.state, "event_bus", _CapturingBus(), raising=False)

    resp = await api_client.put(
        f"/api/v1/templates/{seeded['agent_id']}",
        headers=auth_headers,
        json={"is_active": True},
    )
    assert resp.status_code == 200, resp.text

    events = [payload for name, payload in published if name == "template:updated"]
    assert events, f"No template:updated event was published. Captured: {published!r}"
    payload = events[-1]

    assert payload["may_be_stale"] is True, (
        "The template:updated event broadcast the TENANT-WIDE staleness while the "
        "response beside it carried the product-aware one. The UI refreshes the "
        "badge from this event, so editing an agent would show product B as up to "
        "date on the strength of product A's export."
    )
    assert payload["may_be_stale"] == resp.json()["may_be_stale"], (
        "The event and the HTTP response disagree about the same agent in the same "
        "request. Whichever is right, two answers reaching the UI from one call is "
        "the bug."
    )
