# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""A tenant-isolation stop-condition was downgraded to a log line by a broad catch.

``get_agent_templates`` narrows its template list to the ones assigned to the
product, and wraps that call in
``except (OSError, RuntimeError, ValueError, TypeError, AttributeError)`` whose
comment reads "Non-fatal: fall back to showing all templates". That fallback is
deliberate and correct for a transient failure.

But ``TenantIsolationError`` subclasses ``RuntimeError``
(``tenant_guard.TenantIsolationError``), so an isolation stop-condition matched
the broad tuple, became a ``logger.warning``, and the tool returned a normal
result.

**Which guard raise can actually reach that block.** The callee
(``ProductAgentAssignmentRepository.get_active_template_ids_for_product``) wraps
its ``session.execute`` in ``tenant_session_context``, which sets the session's
tenant key with source ``"service"``. That makes the "tenant context required"
raise and the flush-derived raise unreachable inside this block. What remains is
a ``_bypass_covers`` coverage miss: under an active ``tenant_isolation_bypass``
the outer template query's model set is covered while the inner join, which also
touches ``ProductAgentAssignment``, is not -- raising "Tenant isolation bypass
does not cover: ProductAgentAssignment".

Both halves of the path are covered here, because narrowing the tool's catch
alone does not deliver the stop-condition (see the fetch_context section below).

The tests are two pairs, and each pair must stay together:

* **propagates / escapes** -- the stop-condition leaves the tool, and leaves the
  dispatch loop above it
* **falls back / still reported** -- an ordinary error keeps its previous
  behaviour at both layers, unchanged

The second of each pair is the guard against the lazy fix. Deleting either broad
catch outright would make the first pass while destroying the transient-failure
handling those catches were actually written for.

**Why the exception is injected rather than provoked through the real guard.**
Provoking a genuine bypass-coverage miss requires standing up an outer bypass
whose model set excludes the join's second model; injecting the real exception
type at the real call site is the deterministic stand-in for the one thing under
test here -- how these ``except`` clauses classify it.

Parallel-safe: unique tenant per test, rollback-isolated ``db_session``,
``monkeypatch`` for the injection (no module-level mutable state).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tenant_guard import TenantIsolationError
from giljo_mcp.tools.context_tools.fetch_context import fetch_context
from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates


# `import ... as` yields the function shadowed by the package __init__ re-export,
# so reach the module through sys.modules to patch its collaborators.
fetch_context_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def product(db_session, tenant_key):
    row = Product(
        id=str(uuid4()),
        name=f"Isolation Propagation Product {uuid4().hex[:6]}",
        description="agent-template isolation-propagation fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest_asyncio.fixture
async def assigned_roster(db_session, tenant_key, product):
    """Three live templates, exactly one of them assigned to the product.

    This shape makes the fallback observable: when the assignment filter runs it
    narrows to one name, and when it is skipped all three come back. A roster
    with no assignment would return the same set either way, and the fallback
    assertion would be vacuous.
    """
    templates = []
    for name in ("implementer", "tester", "reviewer"):
        row = AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"{name}_{uuid4().hex[:6]}",
            role=name.title(),
            description=f"{name} description",
            is_active=True,
        )
        db_session.add(row)
        templates.append(row)
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            template_id=templates[0].id,
            is_active=True,
        )
    )
    await db_session.commit()
    return templates


async def _names(db_session, tenant_key, product) -> set[str]:
    result = await get_agent_templates(
        product_id=product.id,
        tenant_key=tenant_key,
        detail="basic",
        _test_session=db_session,
    )
    return {entry["name"] for entry in result["data"]}


def _raise_inside_guarded_block(monkeypatch, exc: Exception) -> None:
    """Make the assignment-filter call raise ``exc`` at its real call site."""

    async def _boom(self, session, product_id, tenant_key):
        raise exc

    monkeypatch.setattr(
        ProductAgentAssignmentRepository,
        "get_active_template_ids_for_product",
        _boom,
    )


async def test_tenant_isolation_error_propagates_out_of_the_tool(
    db_session, tenant_key, product, assigned_roster, monkeypatch
):
    """THE DEFECT. An isolation stop-condition must not be downgraded to a warning.

    Before the fix the broad tuple matched it (``TenantIsolationError`` IS-A
    ``RuntimeError``), the tool logged a warning and returned a normal roster,
    and this raises-assertion failed with DID NOT RAISE.
    """
    _raise_inside_guarded_block(monkeypatch, TenantIsolationError("Tenant context required for ORM statement"))

    with pytest.raises(TenantIsolationError):
        await _names(db_session, tenant_key, product)


async def test_ordinary_runtime_error_still_falls_back_to_all_templates(
    db_session, tenant_key, product, assigned_roster, monkeypatch
):
    """THE GUARD. The transient case the catch was written for is unchanged.

    The control assertion runs first, so "all three came back" is proven to be
    the fallback rather than what this fixture returns anyway.
    """
    assert await _names(db_session, tenant_key, product) == {assigned_roster[0].name}, (
        "control failed: the assignment filter did not narrow the roster, so the "
        "fallback assertion below would prove nothing"
    )

    _raise_inside_guarded_block(monkeypatch, RuntimeError("transient connection reset"))

    assert await _names(db_session, tenant_key, product) == {t.name for t in assigned_roster}, (
        "an ordinary RuntimeError no longer falls back to showing all templates -- "
        "narrowing the catch changed behaviour for the transient case it was written for"
    )


# --------------------------------------------------------------------------- #
# The dispatch loop above the tool: fetch_context
#
# Narrowing the catch inside get_agent_templates is not sufficient on its own.
# ``fetch_context`` is that tool's ONLY caller (via ``CATEGORY_TOOLS``), and its
# per-category loop catches ``Exception`` and appends
# ``{"category": ..., "error": str(e)}`` to an ``errors`` list. So a propagated
# TenantIsolationError was flattened back into a SUCCESS payload carrying the
# guard's internal text (e.g. "Tenant isolation bypass does not cover:
# ProductAgentAssignment") straight to the calling agent -- the exact string
# class ``api/endpoints/mcp_tools/_base.py`` (_NOT_FOUND_TOOL_ERROR, and the
# BE-3006d note above it) exists to suppress.
#
# The stop-condition has to be re-raised in the loop that flattens it, which is
# also where the class of problem lives: every category's exceptions, not just
# this one tool's, are turned into a success payload there.
# --------------------------------------------------------------------------- #

_FETCH_PRODUCT_ID = "11111111-1111-1111-1111-111111111111"
_FETCH_TENANT_KEY = "tk_sec9353"
_FETCH_CATEGORIES = ["memory_360", "agent_templates", "vision_documents"]


def _patched_loop(raiser):
    """Patch the loop's collaborators, making ``agent_templates`` raise."""

    async def fake_fetch(category: str, **_kwargs):
        if category == "agent_templates":
            raise raiser
        return {"source": category, "data": {"ok": category}, "metadata": {}}

    return (
        patch.object(fetch_context_module, "_fetch_category", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(fetch_context_module, "_load_user_depth_config", new=AsyncMock(return_value={})),
        patch.object(fetch_context_module, "_build_last_modified_map", new=AsyncMock(return_value={})),
    )


async def test_tenant_isolation_error_escapes_fetch_context():
    """THE DEFECT, one layer up. The stop-condition must leave fetch_context.

    Before the fix the broad per-category ``except Exception`` swallowed it and
    returned a success payload whose ``errors`` entry carried the guard's
    internal phrasing to the agent.
    """
    guard_error = TenantIsolationError("Tenant isolation bypass does not cover: ProductAgentAssignment")
    a, b, c, d = _patched_loop(guard_error)

    with a, b, c, d, pytest.raises(TenantIsolationError):
        await fetch_context(
            product_id=_FETCH_PRODUCT_ID,
            tenant_key=_FETCH_TENANT_KEY,
            categories=_FETCH_CATEGORIES,
            db_manager=object(),  # truthy stand-in; every real DB call is patched
        )


async def test_ordinary_category_error_still_reported_and_other_categories_survive():
    """THE GUARD. Per-category error isolation is a real feature and is unchanged.

    An ordinary failure in one category must still be reported in ``errors``
    while every other category returns its data.
    """
    a, b, c, d = _patched_loop(RuntimeError("transient connection reset"))

    with a, b, c, d:
        response = await fetch_context(
            product_id=_FETCH_PRODUCT_ID,
            tenant_key=_FETCH_TENANT_KEY,
            categories=_FETCH_CATEGORIES,
            db_manager=object(),
        )

    assert [e["category"] for e in response.get("errors", [])] == ["agent_templates"], (
        "an ordinary per-category error is no longer reported in the errors block -- "
        f"per-category isolation was broken by the narrowing. got={response.get('errors')}"
    )
    assert "agent_templates" not in response["categories_returned"]
    assert response["data"]["memory_360"] == {"ok": "memory_360"}
    assert response["data"]["vision_documents"] == {"ok": "vision_documents"}
