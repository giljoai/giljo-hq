# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9557: the agent-export resolver picked an ARBITRARY shown product, not
"the" active one.

``product_agent_selection.active_product_template_ids`` (and its two siblings,
``build_export_context`` and ``active_product_export_timestamps``) resolved
"the tenant's active product" with ``.first()`` on ``Product.is_active``,
under a docstring claiming exactly one product per tenant can be active,
"enforced by the partial unique index idx_product_single_active_per_tenant".
That index was dropped in ce_0100 (BE-9525b/FE-9524): several products may be
``is_active`` (shown) at once, so ``.first()`` returns whichever row the
planner happens to return first -- arbitrary, and silently wrong on any
multi-shown tenant.

The fix resolves via ``is_default`` (``ProductRepository.get_default_product``)
instead -- the column FE-9524 introduced specifically to answer "where does an
unscoped read resolve", independent of is_active/shown, still backed by a
real partial unique index (idx_product_single_default_per_tenant).

Deterministic repro (no reliance on unspecified row order): the DEFAULT
product is made NOT shown (``is_active=False``) and the SHOWN product is made
NOT default. Under the old ``.first() on is_active`` query, the default
product cannot be selected at all -- it fails the WHERE clause outright. Under
the fixed ``is_default`` resolution, the shown product is irrelevant and the
hidden default product is exactly what comes back. This is not "usually
right"; the two queries are structurally forced to disagree here.

The second half (test_list_agent_templates_*) is the sibling defect: giljo_setup
resolves a product binding (BE-9523c) but never threaded it into template
selection -- ``list_agent_templates`` had no ``product_id`` parameter at all.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor._setup_tools import SetupMiscMixin


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


async def _make_product(db_session, tenant_key, *, is_active: bool, is_default: bool, name: str) -> Product:
    row = Product(
        id=str(uuid4()),
        name=name,
        description="BE-9557 export routing fixture",
        tenant_key=tenant_key,
        is_active=is_active,
        is_default=is_default,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _make_template(db_session, tenant_key, name: str) -> AgentTemplate:
    row = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=f"{name}_{uuid4().hex[:6]}",
        role=name.title(),
        description=f"{name} description",
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _assign(db_session, tenant_key, product, template) -> ProductAgentAssignment:
    row = ProductAgentAssignment(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        template_id=template.id,
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
async def two_products_disjoint_assignments(db_session, tenant_key):
    """A hidden DEFAULT product and a shown NON-default product, each with its
    own, disjoint set of assigned templates."""
    default_product = await _make_product(db_session, tenant_key, is_active=False, is_default=True, name="Default")
    shown_product = await _make_product(db_session, tenant_key, is_active=True, is_default=False, name="Shown")

    default_template = await _make_template(db_session, tenant_key, "default_agent")
    shown_template = await _make_template(db_session, tenant_key, "shown_agent")

    await _assign(db_session, tenant_key, default_product, default_template)
    await _assign(db_session, tenant_key, shown_product, shown_template)

    return {
        "default_product": default_product,
        "shown_product": shown_product,
        "default_template": default_template,
        "shown_template": shown_template,
    }


# ---------------------------------------------------------------------------
# active_product_template_ids / build_export_context / active_product_export_timestamps
# ---------------------------------------------------------------------------


async def test_active_product_template_ids_resolves_default_not_arbitrary_shown(
    db_session, tenant_key, two_products_disjoint_assignments
):
    from giljo_mcp.repositories.product_agent_selection import active_product_template_ids

    fx = two_products_disjoint_assignments
    ids = await active_product_template_ids(db_session, tenant_key)

    assert ids == {fx["default_template"].id}, (
        "active_product_template_ids must resolve the DEFAULT product's template set "
        f"(is_default=True), not whichever is_active row .first() happened to return. got={ids}"
    )


async def test_build_export_context_identifies_default_product(
    db_session, tenant_key, two_products_disjoint_assignments
):
    from giljo_mcp.repositories.product_agent_selection import build_export_context

    fx = two_products_disjoint_assignments
    ctx = await build_export_context(db_session, tenant_key)

    assert ctx is not None
    assert ctx.product_id == str(fx["default_product"].id), (
        "build_export_context must identify the DEFAULT product as the export owner, "
        f"not the arbitrary is_active row. got product_id={ctx.product_id}"
    )


async def test_active_product_export_timestamps_scopes_to_default_product(
    db_session, tenant_key, two_products_disjoint_assignments
):
    from giljo_mcp.repositories.product_agent_selection import (
        active_product_export_timestamps,
        record_product_export,
    )

    fx = two_products_disjoint_assignments
    export_time = datetime.now(UTC)

    # Stamp the DEFAULT product's export explicitly.
    await record_product_export(
        db_session,
        str(fx["default_product"].id),
        tenant_key,
        [fx["default_template"].id],
        export_time,
    )
    await db_session.flush()

    stamps = await active_product_export_timestamps(db_session, tenant_key)

    assert fx["default_template"].id in stamps, (
        "active_product_export_timestamps must scope to the DEFAULT product, "
        f"whose junction row was just stamped. got={stamps}"
    )
    assert stamps[fx["default_template"].id] is not None


# ---------------------------------------------------------------------------
# list_agent_templates -- product_id threading (SetupMiscMixin)
# ---------------------------------------------------------------------------


class _TestSessionDbManager:
    """Minimal db_manager stand-in returning the rolled-back test session
    (matches tests/api/test_be6137_template_softdelete_mcp_boundary.py)."""

    def __init__(self, session) -> None:
        self._session = session

    @contextlib.asynccontextmanager
    async def get_session_async(self, **_kwargs):
        yield self._session


class _ListTemplatesHarness(SetupMiscMixin):
    """Minimal SetupMiscMixin host exercising list_agent_templates' real SQL.

    Inherits SetupMiscMixin (not just standing in for it) so ``self._resolve_product_binding``
    -- the same product-binding validation ``bootstrap_setup`` uses -- is available.
    ``list_agent_templates`` itself opens sessions via ``self.get_session_async()``
    directly (not ``self.db_manager``); ``_resolve_product_binding`` constructs its
    own ``ProductService(db_manager=self.db_manager, ...)``, which opens sessions
    via ``self.db_manager.get_session_async()``. Both must proxy to the same
    rolled-back test session so the two code paths see each other's writes.
    """

    def __init__(self, session) -> None:
        self._session = session
        self.db_manager = _TestSessionDbManager(session)
        self.tenant_manager = None

    @contextlib.asynccontextmanager
    async def get_session_async(self, **_kwargs):
        yield self._session


async def test_list_agent_templates_with_product_id_returns_requested_products_set(
    db_session, tenant_key, two_products_disjoint_assignments
):
    """Two SHOWN products, different assignments each: passing product_id must
    narrow the export to exactly the REQUESTED product's set.

    FAILS on unfixed code two ways: (1) list_agent_templates has no
    product_id parameter at all (TypeError), and (2) even ignoring that, the
    no-product_id fallback would pick an arbitrary is_active row rather than
    the one actually requested.
    """
    fx = two_products_disjoint_assignments
    # Make BOTH products shown, so a no-product_id call would be genuinely
    # ambiguous -- the test must prove product_id was HONOURED, not that it
    # happened to match a fallback.
    fx["default_product"].is_active = True
    await db_session.flush()

    harness = _ListTemplatesHarness(db_session)
    result = await harness.list_agent_templates(tenant_key, "claude_code", product_id=str(fx["shown_product"].id))

    contents = [agent["content"] for agent in result["agents"]]
    assert len(contents) == 1, f"expected exactly one exported agent, got {len(contents)}"
    assert fx["shown_template"].name in contents[0], (
        "list_agent_templates(product_id=...) must export exactly the requested "
        f"product's assigned templates. got filenames={[a['filename'] for a in result['agents']]}"
    )
    assert fx["default_template"].name not in contents[0], (
        "the OTHER product's template leaked into the requested product's export"
    )


async def test_list_agent_templates_rejects_foreign_product_id(db_session, tenant_key):
    """A product_id from another tenant must be rejected, not silently ignored
    (agent input is untrusted -- membership must be validated before it reaches
    the selection layer)."""
    from giljo_mcp.exceptions import ValidationError

    await _make_template(db_session, tenant_key, "solo_agent")
    await db_session.flush()

    harness = _ListTemplatesHarness(db_session)
    with pytest.raises(ValidationError):
        await harness.list_agent_templates(tenant_key, "claude_code", product_id=str(uuid4()))
