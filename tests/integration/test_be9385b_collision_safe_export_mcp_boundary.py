# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9385b -- exported agents must not be able to overwrite each other.

BE-9385a made export selection product-true: the active product decides WHICH
agents ship. It did not change what they are CALLED. So the same agent, shared
by two products, still exports as ``<agent-name>.md`` from both -- byte-identical
filenames pointing at different product contexts. Install one, then the other,
and the second silently replaces the first. Nothing warns, because nothing on
disk records which product an installed file belongs to.

Operator's framing: "agents can not step on each other; naming for export is
important; no overwrites as a protection layer."

Two properties are asserted here, and they are separate requirements:

1. **Deterministic, product-qualified names.** The same agent exported under two
   different products must produce two different filenames, so the two installs
   coexist instead of racing for one path.

2. **An ownership marker in the rendered bytes, and NOWHERE ELSE.** The marker is
   what lets an installer tell "this file is mine, refresh it" from "this file is
   the user's, leave it alone" -- the distinction the current whole-directory
   Overwrite-all/Skip-all prompt cannot make. It is injected at RENDER time and
   must never reach a template row: the byte-equality heal migrations
   (ce_0049/ce_0084/ce_0085/ce_0090) compare stored template text against a
   seeded literal, and a marker stamped into ``system_instructions`` would break
   every one of them on the next self-hosted upgrade. ``test_the_marker_is_never
   _persisted_into_the_template_row`` is that invariant's guard, and it is the
   one test here that protects data rather than behaviour.

Layer: MCP boundary, per the house bug-fix rule -- the failing surface is what an
agent receives from ``giljo_setup``, so the assertions are made on the wire
through ``create_connected_server_and_client_session`` and the real ``@mcp.tool``
wrapper. The fixture mirrors
``test_be9385a_product_bound_agent_selection_mcp_boundary.py`` deliberately: the
chain under test is the shipped one, not a reconstruction of it.

Why the ``web_sandbox`` harness: it takes ``giljo_setup``'s no-filesystem branch,
which returns the selected templates INLINE (filename + content) instead of a
staged ZIP URL, so both the name and the rendered bytes are assertable on the
wire. ``chat`` would not work -- ``WORKSPACE_NONE`` strips the per-agent
``filename``, which is the very thing property 1 is about.

Parallel-safe: fresh tenant_key per test, rolled-back ``db_session``, no
module-level mutable state.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# The marker's stable opening token. Asserted as a LITERAL here on purpose: an
# import of the (not yet existing) production constant would make this file fail
# with ImportError, which proves only that a symbol is new -- not that the export
# is unsafe. The behavioural red is the point. ``test_the_test_and_the_renderer
# _agree_on_the_marker_token`` pins the literal against the production constant
# once it exists, so the two can never drift apart afterwards.
MARKER_TOKEN = "giljo-managed:"


class _TestSessionDbManager:
    """db_manager stand-in that hands out the rolled-back test session.

    Same pattern as the BE-9385a boundary test: the tool under test must see rows
    written inside this test's transaction rather than opening a separate pool
    connection that cannot see them.
    """

    def __init__(self, session) -> None:
        self._session = session

    @contextlib.asynccontextmanager
    async def get_session_async(self, **_kwargs):
        yield self._session


def _template(tenant_key: str, name: str) -> AgentTemplate:
    """A minimally-valid, tenant-ACTIVE template row."""
    return AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant_key,
        name=name,
        role="custom",
        category="custom",
        system_instructions="# BE-9385b boundary test template",
        user_instructions="body",
        tool="claude",
        cli_tool="claude",
        is_active=True,
        version="1.0.0",
    )


def _product(tenant_key: str, name: str, *, is_active: bool) -> Product:
    return Product(id=str(uuid4()), tenant_key=tenant_key, name=name, is_active=is_active)


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


async def _exported_agents(client_factory) -> list[dict[str, Any]]:
    """Drive ``giljo_setup`` over the real MCP transport; return the shipped agents."""
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
    return list(payload.get("agents", []))


async def _shared_agent_in_two_products(db_session, tenant_key: str):
    """One agent, two products, both products referencing it. Returns (template, a, b).

    This is the collision scenario in its simplest honest form. It is not
    contrived: the junction's whole purpose is that one tenant-wide template can
    serve several products, and activating a product bulk-assigns every active
    template to it -- so a shared agent is the DEFAULT state, not an edge case.
    """
    suffix = uuid4().hex[:8]
    shared = _template(tenant_key, f"be9385b-shared-{suffix}")

    # Only one product may be active per tenant (partial unique index
    # idx_product_single_active_per_tenant), so B starts inactive and is promoted
    # between the two exports -- the operator's actual "switch products" action.
    product_a = _product(tenant_key, f"Alpha {suffix}", is_active=True)
    product_b = _product(tenant_key, f"Beta {suffix}", is_active=False)

    db_session.add_all([shared, product_a, product_b])
    await db_session.flush()

    db_session.add_all(
        [
            _assignment(tenant_key, product_a, shared),
            _assignment(tenant_key, product_b, shared),
        ]
    )
    await db_session.flush()

    return shared, product_a, product_b


async def test_the_same_agent_exported_from_two_products_gets_distinct_filenames(setup_tool_client, db_session):
    """THE HEADLINE. One agent, two products, two filenames -- so the installs coexist.

    Fail-first: today both exports name the file ``<agent-name>.md``, so the two
    are byte-identical strings. Installing the second one on top of the first is
    not a conflict the installer can even detect -- it is the same path.
    """
    client_factory, tenant_key = setup_tool_client
    shared, product_a, product_b = await _shared_agent_in_two_products(db_session, tenant_key)

    from_a = await _exported_agents(client_factory)

    product_a.is_active = False
    await db_session.flush()
    product_b.is_active = True
    await db_session.flush()

    from_b = await _exported_agents(client_factory)

    name_a = {a["filename"] for a in from_a}
    name_b = {a["filename"] for a in from_b}

    # Guard the premise: if the agent stopped shipping from either product the
    # collision assertion below would pass vacuously.
    assert len(name_a) == 1 and len(name_b) == 1, (
        "Premise broken -- the shared agent must ship from BOTH products. "
        f"product A shipped {sorted(name_a)}, product B shipped {sorted(name_b)}."
    )

    assert not (name_a & name_b), (
        "THE COLLISION: the same agent exported under two different products lands on "
        "the SAME filename, so installing the second silently overwrites the first.\n"
        f"  from {product_a.name}: {sorted(name_a)}\n"
        f"  from {product_b.name}: {sorted(name_b)}\n"
        "Exported names must be product-qualified so the two installs coexist."
    )

    # Product-qualified, not merely different: the agent must still be
    # recognisable in its own filename, or the user cannot tell what they
    # installed. A random discriminator would satisfy the assertion above.
    for filename in name_a | name_b:
        assert shared.name in filename, (
            f"{filename!r} no longer contains the agent's own name {shared.name!r}. "
            "The product qualifier must be added to the name, not replace it."
        )


async def test_every_exported_agent_carries_an_ownership_marker(setup_tool_client, db_session):
    """Each rendered agent must declare who owns it, and the two products must differ.

    Without this, a GiljoAI export and a user's hand-written agent are
    indistinguishable on disk, which is exactly why today's install prompt has to
    ask about the whole directory and why answering "Overwrite" destroys
    user-authored files.
    """
    client_factory, tenant_key = setup_tool_client
    _shared, product_a, product_b = await _shared_agent_in_two_products(db_session, tenant_key)

    from_a = await _exported_agents(client_factory)

    product_a.is_active = False
    await db_session.flush()
    product_b.is_active = True
    await db_session.flush()

    from_b = await _exported_agents(client_factory)

    content_a = from_a[0]["content"]
    content_b = from_b[0]["content"]

    for label, content in ((product_a.name, content_a), (product_b.name, content_b)):
        assert MARKER_TOKEN in content, (
            f"The agent exported for {label!r} carries no {MARKER_TOKEN!r} ownership marker, "
            "so an installer cannot tell it apart from a file the user wrote by hand."
        )

    marker_a = next(line for line in content_a.splitlines() if MARKER_TOKEN in line)
    marker_b = next(line for line in content_b.splitlines() if MARKER_TOKEN in line)

    assert product_a.id in marker_a, f"marker does not name its product: {marker_a!r}"
    assert product_b.id in marker_b, f"marker does not name its product: {marker_b!r}"
    assert tenant_key in marker_a, f"marker does not name its tenant: {marker_a!r}"

    assert marker_a != marker_b, (
        "The same agent exported from two products produced an IDENTICAL ownership "
        "marker, so a conflict between them is undetectable at install time.\n"
        f"  {marker_a}\n  {marker_b}"
    )


async def test_the_marker_is_never_persisted_into_the_template_row(setup_tool_client, db_session):
    """LOAD-BEARING. Exporting must not write marker text back into the template.

    ce_0049 / ce_0084 / ce_0085 / ce_0090 heal seeded templates by comparing stored
    text against a byte-exact literal. A marker persisted into any template text
    column would make every one of those comparisons miss, and a self-hoster's
    templates would silently stop healing on upgrade -- a failure that shows up
    releases later, in someone else's install, with no way to trace it back here.

    So the marker lives in the rendered bytes and nowhere else, and this test
    exists to keep it that way after the render path is refactored by someone who
    has never read this docstring.
    """
    client_factory, tenant_key = setup_tool_client
    shared, _product_a, _product_b = await _shared_agent_in_two_products(db_session, tenant_key)

    exported = await _exported_agents(client_factory)
    assert exported, "premise broken -- nothing was exported, so nothing was rendered"

    # Read the COLUMNS back, not the ORM object. A column select goes to the
    # database and yields plain values, so it cannot be satisfied from the
    # identity map and cannot trigger a lazy refresh outside the async context.
    stored = (
        await db_session.execute(
            select(
                AgentTemplate.system_instructions,
                AgentTemplate.user_instructions,
                AgentTemplate.description,
                AgentTemplate.name,
            ).where(AgentTemplate.id == shared.id)
        )
    ).one()

    text_columns = {
        "system_instructions": stored.system_instructions,
        "user_instructions": stored.user_instructions,
        "description": stored.description,
        "name": stored.name,
    }
    for column, value in text_columns.items():
        assert MARKER_TOKEN not in (value or ""), (
            f"Export wrote the ownership marker into AgentTemplate.{column}. The marker is "
            "render-time only -- persisting it breaks the ce_0049/ce_0084/ce_0085/ce_0090 "
            f"byte-equality heals.\n  {column} = {value!r}"
        )
