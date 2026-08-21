# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9420 item 2 -- create_thread's ``product_id`` passthrough, pinned at the boundary.

The project record claimed the MCP wrapper "never exposes product_id, so threads
created by agents can never be product-filtered". Measured against the tree, that
premise is FALSE: the parameter has been declared on the wrapper since BE-6054b
(2026-06-16), it is already in the ``test_be6042d`` param lock, and it binds
end-to-end.

What was missing is this file. The capability shipped two months ago with NOTHING
asserting it, which is precisely how it became possible for a census to conclude it
did not exist. These tests are the durable artefact of item 2 -- they pin the
agent-facing surface and the write, so the next reader does not have to re-derive
either from the source.

Driven over the ACTUAL MCP transport rather than by calling the service, per
AGENTS.md: a wrapper claim proven by monkeypatching ``_call_tool`` away can hide a
break in the real ``_call_tool -> TOOL_DISPATCH -> service`` chain.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    return json.loads(res.content[0].text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def thread_product_client(db_manager, db_session, monkeypatch):
    """``(new_client, tenant_key, own_product_id, foreign_product_id, foreign_project_id)``.

    Two tenants, one product each. The foreign product is a REAL row with a real
    id -- the only thing wrong with it is that it belongs to somebody else, which
    is the only shape that can tell a tenant check apart from a mere FK check.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    foreign_tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]

    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    db_session.add(User(id=str(uuid4()), tenant_key=tenant_key, username=f"be9420_{suffix}"))
    own_product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"BE9420 Own {suffix}")
    foreign_product = Product(id=str(uuid4()), tenant_key=foreign_tenant_key, name=f"BE9420 Foreign {suffix}")
    db_session.add(own_product)
    db_session.add(foreign_product)
    await db_session.flush()
    foreign_project = Project(
        id=str(uuid4()),
        tenant_key=foreign_tenant_key,
        product_id=foreign_product.id,
        name=f"BE9420 Foreign Project {suffix}",
        # tenant_key / name / description / mission are the four NOT NULL columns
        # on projects with no default of their own -- read off the model rather
        # than discovered one IntegrityError at a time.
        description="BE-9420 cross-tenant guard fixture",
        mission="Exists only so a real foreign project id can be offered.",
    )
    db_session.add(foreign_project)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, own_product.id, foreign_product.id, foreign_project.id
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _thread_row(db_session, tenant_key: str, thread_id: str) -> CommThread:
    """Read the thread back INSIDE a tenant context.

    The ORM read is tenant-scoped: outside ``tenant_session_context`` a plain
    ``select(CommThread)`` returns nothing even when the row is present (verified
    against raw SQL, which sees it). Reading without the context would make an
    "is it bound?" assertion fail for the wrong reason -- and, worse, would make a
    "not bound" assertion PASS for the wrong reason.
    """
    with tenant_session_context(db_session, tenant_key):
        return (await db_session.execute(select(CommThread).where(CommThread.id == thread_id))).scalar_one()


async def test_product_id_is_on_the_agent_facing_tool_surface(thread_product_client):
    """The parameter an agent can actually see, read off the live schema.

    Asserted against ``list_tools`` rather than the function signature because the
    signature is not what an agent reads -- a parameter that failed to render into
    the advertised schema would be undiscoverable while looking correct in source.
    """
    new_client, _tk, _own, _foreign, _fproj = thread_product_client

    async with new_client() as session:
        listed = await session.list_tools()

    create_thread = next(t for t in listed.tools if t.name == "create_thread")
    assert "product_id" in create_thread.input_schema.get("properties", {}), (
        "create_thread no longer advertises product_id, so an agent cannot bind a "
        "thread to a product at all (BE-9420 item 2)."
    )


async def test_a_supplied_product_id_binds_the_thread(thread_product_client, db_session):
    """Round-trip: the id reaches the row, not just the response."""
    new_client, tenant_key, own_product_id, _foreign, _fproj = thread_product_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_thread",
            {"subject": "bound thread", "creator_id": "agent-alpha", "product_id": own_product_id},
        )
    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert payload["product_id"] == own_product_id
    row = await _thread_row(db_session, tenant_key, payload["thread_id"])
    assert row.product_id == own_product_id, (
        "create_thread accepted product_id and dropped it before the write -- the "
        "declared-but-absorbed shape BE-9415 found on update_task."
    )


async def test_omitting_product_id_leaves_the_thread_unbound(thread_product_client, db_session):
    """The control, and it is load-bearing.

    Without it, the test above would still pass if threads bound to some ambient
    product regardless of the argument -- which would make the binding assertion
    prove nothing about the parameter.
    """
    new_client, tenant_key, _own, _foreign, _fproj = thread_product_client

    async with new_client() as session:
        result = await session.call_tool("create_thread", {"subject": "standalone", "creator_id": "agent-alpha"})
    assert result.is_error is False, _error_text(result)

    row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
    assert row.product_id is None, "a thread created without product_id must stay standalone"


async def test_another_tenants_product_id_cannot_bind(thread_product_client, db_session):
    """Agent input is not trusted: a foreign product id must not become a link.

    ``product_id`` arrives from an agent, and the repository already applies exactly
    this reasoning to ``sequence_run_id`` in its own docstring -- *"a run id from
    another tenant would otherwise be accepted by the constraint while silently
    creating a cross-tenant link"*. The FK alone cannot tell the two apart: the
    foreign id is a real, satisfiable row.

    Either the call is refused, or the thread is left unbound. What must NOT happen
    is a stored link from this tenant's thread to another tenant's product.
    """
    new_client, tenant_key, _own, foreign_product_id, _fproj = thread_product_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_thread",
            {"subject": "cross tenant", "creator_id": "agent-alpha", "product_id": foreign_product_id},
        )

    if result.is_error:
        return  # Refused at the boundary — the strictest acceptable outcome.

    row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
    assert row.tenant_key == tenant_key
    assert row.product_id != foreign_product_id, (
        f"create_thread stored a link from tenant {tenant_key}'s thread to a product "
        f"owned by another tenant ({foreign_product_id}). The FK is satisfied, which "
        "is why nothing raised -- but the row is a cross-tenant reference."
    )


async def test_another_tenants_project_id_cannot_bind(thread_product_client, db_session):
    """``project_id`` arrives at the same boundary and is written by the same call.

    Fixed at the class rather than the instance: both optional ids on
    ``create_thread`` are agent input, both are stored unvalidated, and a guard on
    only the one this project happened to name would leave the identical hole open
    one argument to the left.
    """
    new_client, tenant_key, _own, _fprod, foreign_project_id = thread_product_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_thread",
            {"subject": "cross tenant project", "creator_id": "agent-alpha", "project_id": foreign_project_id},
        )

    if result.is_error:
        return

    row = await _thread_row(db_session, tenant_key, _payload(result)["thread_id"])
    assert row.project_id != foreign_project_id, (
        f"create_thread anchored tenant {tenant_key}'s thread to a project owned by "
        f"another tenant ({foreign_project_id})."
    )
