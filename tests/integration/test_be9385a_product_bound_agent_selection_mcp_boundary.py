# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9385a -- the agent export must follow the ACTIVE PRODUCT, not the tenant.

The incident (live operator report, LAN CE): agents tuned while product A was
active were exported into product B. The root cause is not a lost association --
the product association has no representation on any export path at all. Every
export site selects ``WHERE tenant_key AND is_active AND deleted_at IS NULL``
with no product term, so toggling the active product cannot change what ships.

The ``product_agent_assignments`` junction (model + service + repository + REST
all present since the IMP-0007 rollback) is the mechanism that was built for
this and never made authoritative.

Layer: this is an MCP-boundary regression test, per the house bug-fix rule --
the failing surface is what an agent receives from ``giljo_setup``, so the
assertion is made on the wire through ``create_connected_server_and_client_session``
and the real ``@mcp.tool`` wrapper, not against a service in isolation.

Why the ``web_sandbox`` harness: it takes ``giljo_setup``'s no-filesystem branch
(``_setup_tools.py:101-134``), which returns the selected templates INLINE in the
tool result instead of a staged ZIP URL -- so the exported set is directly
assertable on the wire. ``web_sandbox`` rather than ``chat`` because the
``WORKSPACE_NONE`` branch strips each agent's ``filename`` (it has nowhere to put
a file), and ``filename`` is how this test identifies which agents shipped.

Parallel-safe: fresh tenant_key per test, rolled-back ``db_session``, no
module-level mutable state.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.product_slug import slugify_product_name
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


class _TestSessionDbManager:
    """db_manager stand-in that hands out the rolled-back test session.

    Mirrors the established pattern in
    ``tests/api/test_be6137_template_softdelete_mcp_boundary.py`` so the tool
    under test sees rows written inside this test's transaction instead of
    opening a separate pool connection that cannot see them.
    """

    def __init__(self, session) -> None:
        self._session = session

    @contextlib.asynccontextmanager
    async def get_session_async(self, **_kwargs):
        yield self._session


def _template(tenant_key: str, name: str) -> AgentTemplate:
    """A minimally-valid, tenant-ACTIVE template row.

    Every template here is ``is_active=True`` at the tenant level on purpose:
    the whole point is that tenant-active is not the same question as
    "active for the product I am working in".
    """
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        role="custom",
        category="custom",
        system_instructions="# BE-9385a boundary test template",
        user_instructions="body",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        version="1.0.0",
    )


def _product(tenant_key: str, name: str, *, is_active: bool) -> Product:
    return Product(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        is_active=is_active,
    )


def _assignment(tenant_key: str, product: Product, template: AgentTemplate, *, is_active: bool = True):
    return ProductAgentAssignment(
        id=str(uuid4()),
        product_id=product.id,
        template_id=template.id,
        tenant_key=tenant_key,
        is_active=is_active,
    )


@pytest_asyncio.fixture
async def setup_tool_client(db_session, monkeypatch):
    """Wire the real ToolAccessor (bound to the rolled-back session) into the
    in-memory MCP transport and pin the resolved tenant.

    Yields ``(client_factory, tenant_key)``.
    """
    from api import app_state
    from api.endpoints.mcp_sdk_server import mcp
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()

    tenant_key = TenantManager.generate_tenant_key()
    db_manager = _TestSessionDbManager(db_session)
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _exported_filenames(client_factory) -> set[str]:
    """Drive ``giljo_setup`` over the real MCP transport; return the shipped agent filenames."""
    async with client_factory() as client:
        result = await client.call_tool(
            "giljo_setup",
            {"platform": "claude_code", "harness": "web_sandbox"},
        )

    assert not result.is_error, f"giljo_setup errored on the wire: {result.content}"

    payload: dict[str, Any] = result.structured_content or {}
    assert payload.get("mode") == "inline", (
        "Expected giljo_setup's no-filesystem inline branch (it returns the selected "
        f"templates in-band); got mode={payload.get('mode')!r}."
    )
    return {a["filename"] for a in payload.get("agents", [])}


async def test_export_follows_the_active_product(setup_tool_client, db_session):
    """THE INCIDENT. Two products with disjoint junction sets must export different agents.

    Fail-first: against tenant-global selection both activations return all four
    templates, so product A's tuned agents ship into product B -- exactly what the
    operator hit.
    """
    client_factory, tenant_key = setup_tool_client

    suffix = uuid4().hex[:8]
    t_a1 = _template(tenant_key, f"be9385a-a1-{suffix}")
    t_a2 = _template(tenant_key, f"be9385a-a2-{suffix}")
    t_b1 = _template(tenant_key, f"be9385a-b1-{suffix}")
    t_b2 = _template(tenant_key, f"be9385a-b2-{suffix}")

    # Only ONE product may be active per tenant (partial unique index
    # idx_product_single_active_per_tenant), so B starts inactive and is
    # promoted below -- which is precisely the operator's "toggle products" step.
    product_a = _product(tenant_key, f"Product A {suffix}", is_active=True)
    product_b = _product(tenant_key, f"Product B {suffix}", is_active=False)

    db_session.add_all([t_a1, t_a2, t_b1, t_b2, product_a, product_b])
    await db_session.flush()

    db_session.add_all(
        [
            _assignment(tenant_key, product_a, t_a1),
            _assignment(tenant_key, product_a, t_a2),
            _assignment(tenant_key, product_b, t_b1),
            _assignment(tenant_key, product_b, t_b2),
        ]
    )
    await db_session.flush()

    # BE-9385b: exported names are product-qualified (``<agent>--<product-slug>.md``)
    # so one agent shared by two products installs twice instead of overwriting
    # itself. Only the filename SHAPE moved -- every selection assertion below is
    # unchanged, and that is what this test is actually about.
    slug_a = slugify_product_name(product_a.name)
    slug_b = slugify_product_name(product_b.name)
    expected_a = {f"{t_a1.name}--{slug_a}.md", f"{t_a2.name}--{slug_a}.md"}
    expected_b = {f"{t_b1.name}--{slug_b}.md", f"{t_b2.name}--{slug_b}.md"}

    shipped_with_a_active = await _exported_filenames(client_factory)
    assert shipped_with_a_active == expected_a, (
        "Export ignored the active product. With product A active it must ship A's "
        f"assigned agents only.\n  expected: {sorted(expected_a)}\n  got:      "
        f"{sorted(shipped_with_a_active)}"
    )

    # Toggle the active product -- the operator's exact action.
    product_a.is_active = False
    await db_session.flush()
    product_b.is_active = True
    await db_session.flush()

    shipped_with_b_active = await _exported_filenames(client_factory)
    assert shipped_with_b_active == expected_b, (
        "Toggling the active product did not change the export. This is the reported "
        "incident: product A's tuned agents leak into product B.\n"
        f"  expected: {sorted(expected_b)}\n  got:      {sorted(shipped_with_b_active)}"
    )

    assert not (shipped_with_a_active & shipped_with_b_active), (
        "The two products' exports overlap despite disjoint junction sets: "
        f"{sorted(shipped_with_a_active & shipped_with_b_active)}"
    )


async def test_empty_junction_product_exports_the_tenant_active_set(setup_tool_client, db_session):
    """LOAD-BEARING TOLERANCE. A product with zero junction rows must export exactly as today.

    Activation-time assignment is best-effort try/except
    (``product_lifecycle_service.py:202-207``), and products created before the
    junction existed never got rows at all. A naive "junction says nothing means
    nothing is active" would hand those installs an EMPTY export -- a 404 where
    agents used to be. This test is green before the fix and must stay green
    after it; it is the one that protects a paying customer.
    """
    client_factory, tenant_key = setup_tool_client

    suffix = uuid4().hex[:8]
    t_one = _template(tenant_key, f"be9385a-tol1-{suffix}")
    t_two = _template(tenant_key, f"be9385a-tol2-{suffix}")
    product = _product(tenant_key, f"Untouched Product {suffix}", is_active=True)

    db_session.add_all([t_one, t_two, product])
    await db_session.flush()
    # Deliberately NO ProductAgentAssignment rows.

    shipped = await _exported_filenames(client_factory)

    slug = slugify_product_name(product.name)
    assert shipped == {f"{t_one.name}--{slug}.md", f"{t_two.name}--{slug}.md"}, (
        "A product with no junction rows must fall back to the tenant-active set. "
        f"Got {sorted(shipped)} -- an empty or reduced export here means every "
        "pre-junction install goes dark on upgrade."
    )
