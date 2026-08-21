# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9411 -- create_task / create_project must be able to name their product.

The defect, measured live on the test-install box 2026-08-13: both create tools bind
to whatever product is *globally active on the server at that instant*. The
active product is mutable shared state -- another session, or the operator
toggling the dashboard, changes it under a running agent -- so a staged
orchestrator filed a task onto a product that was not its own, with no error and
nothing in the response that made the wrong landing visible.

The failing layer is the MCP boundary: the tools had no product parameter at all,
so the binding tests here drive the REAL in-memory transport
(``create_connected_server_and_client_session``) rather than calling the service
methods directly. A service-level binding test would have proved nothing --
``create_project_for_mcp`` already accepted a ``product_id``; it was the
``@mcp.tool`` wrapper that never advertised or forwarded one. The one exception is
``TestPreExistingServicePathIsValidatedToo``, which is deliberately at the service
entry point, because the missing VALIDATION on that already-existing parameter is a
second defect living one layer down.

Five properties are pinned:

* **Explicit wins over ambient** -- a create naming ``product_id`` lands there
  even while a DIFFERENT product is active.
* **Omitted still follows active** -- the documented default is unchanged
  (back-compat; no migration, no behavior change for existing callers).
* **The race itself** -- flipping the active product between two creates in one
  session leaves the explicit create untouched and carries the default create
  with it. Both halves are the contract, so both are pinned.
* **A foreign or unknown product_id is REJECTED, never silently absorbed** --
  the membership check is tenant-scoped, and a rejection must write nothing at
  all (in particular it must not quietly fall back to the active product, which
  would recreate the original defect while looking like it had worked).
* **The pre-existing service-layer parameter is validated too** -- not only the
  new wrapper param, so a caller reaching the method directly cannot bypass it.

Transport/DB pattern mirrors ``test_be9016_another_project_active_mcp_boundary.py``:
a real ``ToolAccessor`` over the real ``db_manager`` (these adapters commit through
their own sessions, so an injected rolled-back session would not see the seeded
products). Parallel-safe: every test mints a fresh ``tenant_key`` and deletes its
own rows in a ``finally`` block; no module-level mutable state, no ordering
dependencies.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _content_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _assert_clean_membership_rejection(call_tool_result, product_id: str) -> None:
    """The refusal must come from the membership check, and must be agent-actionable.

    Asserting only ``isError`` is too weak: a cross-tenant id is also caught further
    down (FK / tenant guard), so a test that checks nothing else stays green even
    when the tenant-scoped lookup is removed -- measured, not assumed (mutation probe
    C). Pinning the wording pins the LAYER: a clean 422 that names the rejected id,
    not the generic sanitized internal-error text a deeper failure produces.
    """
    text = _content_text(call_tool_result)
    assert "was not found for this account" in text, f"expected the membership-check rejection, got: {text!r}"
    assert product_id in text, f"the rejection must name the id it refused: {text!r}"
    assert "internal error" not in text.lower(), f"rejection was sanitized as a server error: {text!r}"


async def _seed_product(db_manager, tenant_key: str, *, label: str, is_active: bool) -> tuple[str, str]:
    """Commit one product. Returns (product_id, product_name)."""
    product_id = str(uuid4())
    name = f"BE9411 {label} {uuid4().hex[:6]}"
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=name,
                description=f"BE-9411 boundary test product ({label})",
                tenant_key=tenant_key,
                is_active=is_active,
                product_memory={},
            )
        )
        await session.commit()
    return product_id, name


async def _seed_two_products(db_manager, tenant_key: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """The incident's shape: one product ACTIVE, one not.

    Returns ((active_id, active_name), (other_id, other_name)). ``other`` is the
    product an agent means to file against while the dashboard sits on ``active``.
    """
    active = await _seed_product(db_manager, tenant_key, label="active", is_active=True)
    other = await _seed_product(db_manager, tenant_key, label="intended", is_active=False)
    return active, other


async def _set_active_product(db_manager, tenant_key: str, product_id: str) -> None:
    """Flip which product is active -- the operator's dashboard toggle.

    Two statements, deliberately ordered. ``idx_product_single_active_per_tenant``
    is a partial unique index, and SQLAlchemy batches a mixed set/clear into one
    ``executemany`` whose row order is not guaranteed -- setting the new active
    before clearing the old one violates the index. Clear everything and FLUSH,
    then set the winner, so the deactivation always lands first.
    """
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        products = (await session.execute(select(Product).where(Product.tenant_key == tenant_key))).scalars().all()
        for product in products:
            product.is_active = False
        await session.flush()

        for product in products:
            if product.id == product_id:
                product.is_active = True
        await session.commit()


async def _task_product_id(db_manager, tenant_key: str, task_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        task = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        return task.product_id


async def _project_product_id(db_manager, tenant_key: str, project_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one()
        return project.product_id


async def _count_rows_on_product(db_manager, tenant_key: str, product_id: str) -> tuple[int, int]:
    """(task_count, project_count) currently attached to a product."""
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        tasks = (await session.execute(select(Task).where(Task.product_id == product_id))).scalars().all()
        projects = (await session.execute(select(Project).where(Project.product_id == product_id))).scalars().all()
        return len(tasks), len(projects)


async def _cleanup(db_manager, *tenant_keys: str) -> None:
    for tenant_key in tenant_keys:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
            await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
            await session.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()


# ---------------------------------------------------------------------------
# Fixture: real ToolAccessor over the real db_manager, on the MCP transport
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def create_tools_client(db_manager, monkeypatch):
    """Yield ``(client_factory, tenant_key)`` wired into the live FastMCP server.

    In production ``MCPAuthMiddleware`` puts ``tenant_key`` into the ASGI scope and
    the wrappers read it via ``_resolve_tenant``; the in-memory transport has no
    HTTP scope, so that one seam is monkeypatched. Everything below it -- wrapper
    arg validation, ``_call_tool`` dispatch, the owning services -- is real.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# 1. Explicit product_id beats the ambient active product (the fix)
# ---------------------------------------------------------------------------


class TestExplicitProductIdWins:
    async def test_create_task_with_explicit_product_id_ignores_the_active_product(
        self, create_tools_client, db_manager
    ):
        """The incident, inverted: filing while the dashboard sits elsewhere."""
        client, tenant_key = create_tools_client
        (active_id, _active_name), (intended_id, intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {
                        "title": "file against my own product",
                        "description": "explicit product_id must beat the active product",
                        "product_id": intended_id,
                    },
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"task bound to {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
            assert payload["product_name"] == intended_name
            assert await _task_product_id(db_manager, tenant_key, payload["task_id"]) == intended_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_with_explicit_product_id_ignores_the_active_product(
        self, create_tools_client, db_manager
    ):
        client, tenant_key = create_tools_client
        (active_id, _active_name), (intended_id, intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {
                        "name": "Explicitly bound project",
                        "description": "explicit product_id must beat the active product",
                        "product_id": intended_id,
                    },
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"project bound to {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
            assert payload["product_name"] == intended_name
            assert await _project_product_id(db_manager, tenant_key, payload["project_id"]) == intended_id
        finally:
            await _cleanup(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 2. Omitting product_id still follows the active product (back-compat)
# ---------------------------------------------------------------------------


class TestOmittedProductIdFollowsActive:
    async def test_create_task_without_product_id_uses_the_active_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "default binding", "description": "no product_id supplied"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
            assert await _task_product_id(db_manager, tenant_key, payload["task_id"]) == active_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_without_product_id_uses_the_active_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Default bound project", "description": "no product_id supplied"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
            assert await _project_product_id(db_manager, tenant_key, payload["project_id"]) == active_id
        finally:
            await _cleanup(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 3. The race itself, pinned from both sides
# ---------------------------------------------------------------------------


class TestActiveProductFlipRace:
    async def test_flip_between_two_creates_moves_the_default_and_not_the_explicit(
        self, create_tools_client, db_manager
    ):
        """One session, two creates, an active-product flip in between.

        This is the live incident reproduced end to end. The explicit create must
        be immune to the flip; the default create must follow it (that is the
        documented contract, not a bug -- so it is pinned too, and a future change
        to either half has to come here and say so).
        """
        client, tenant_key = create_tools_client
        (first_active_id, _first_name), (second_id, _second_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                explicit = await mcp_session.call_tool(
                    "create_task",
                    {
                        "title": "pinned to the product I named",
                        "description": "created before the flip, naming the non-active product",
                        "product_id": second_id,
                    },
                )
                assert explicit.is_error is False, _content_text(explicit)

                # The operator toggles the dashboard mid-session.
                await _set_active_product(db_manager, tenant_key, second_id)

                default = await mcp_session.call_tool(
                    "create_task",
                    {"title": "carried by the flip", "description": "created after the flip, no product_id"},
                )
                assert default.is_error is False, _content_text(default)

            explicit_payload = _payload(explicit)
            default_payload = _payload(default)

            # Explicit: unaffected by the flip (it named its product up front).
            assert explicit_payload["product_id"] == second_id
            assert await _task_product_id(db_manager, tenant_key, explicit_payload["task_id"]) == second_id

            # Default: follows the flip -- documented behavior, deliberately pinned.
            assert default_payload["product_id"] == second_id
            assert default_payload["product_id"] != first_active_id
            assert await _task_product_id(db_manager, tenant_key, default_payload["task_id"]) == second_id
        finally:
            await _cleanup(db_manager, tenant_key)


# ---------------------------------------------------------------------------
# 4. Invalid / foreign product_id -> clean rejection, and NOTHING is written
# ---------------------------------------------------------------------------


class TestInvalidProductIdIsRejected:
    async def test_create_task_rejects_another_tenants_product(self, create_tools_client, db_manager):
        """The membership check is tenant-scoped: another tenant's real product id
        must be as unusable as a made-up one, and must not fall back to active."""
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "cross-tenant attempt", "description": "must be refused", "product_id": foreign_id},
                )

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
            tasks_here, _ = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert tasks_here == 0, "a refused create must NOT silently fall back to the active product"
            foreign_tasks, _ = await _count_rows_on_product(db_manager, foreign_tenant_key, foreign_id)
            assert foreign_tasks == 0, "a refused create must not write into the other tenant either"
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_create_project_rejects_another_tenants_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {
                        "name": "Cross-tenant attempt",
                        "description": "must be refused",
                        "product_id": foreign_id,
                    },
                )

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
            _, projects_here = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert projects_here == 0, "a refused create must NOT silently fall back to the active product"
            _, foreign_projects = await _count_rows_on_product(db_manager, foreign_tenant_key, foreign_id)
            assert foreign_projects == 0, "a refused create must not write into the other tenant either"
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_create_task_rejects_unknown_product_id(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        bogus_id = str(uuid4())
        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "bad id", "description": "must be refused", "product_id": bogus_id},
                )

            assert result.is_error is True, f"an unknown product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, bogus_id)
            tasks_here, _ = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert tasks_here == 0, "a refused create must NOT silently fall back to the active product"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_rejects_unknown_product_id(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        bogus_id = str(uuid4())
        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Bad id", "description": "must be refused", "product_id": bogus_id},
                )

            assert result.is_error is True, f"an unknown product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, bogus_id)
            _, projects_here = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert projects_here == 0, "a refused create must NOT silently fall back to the active product"
        finally:
            await _cleanup(db_manager, tenant_key)


class TestPreExistingServicePathIsValidatedToo:
    """The hole predates the MCP parameter, and closing it is the load-bearing half.

    ``create_project_for_mcp`` ALREADY accepted a ``product_id`` before BE-9411 --
    it simply had no caller that passed one, and no validation whatsoever. Exposing
    it through the tool without a membership check would have handed an agent a
    cross-tenant write. So the refusal is pinned at the SERVICE entry point too, not
    only through the wrapper: a future caller reaching this method directly (REST,
    another service, a script) gets the same rejection.
    """

    async def test_create_project_for_mcp_refuses_a_foreign_product_id_directly(self, create_tools_client, db_manager):
        from giljo_mcp.exceptions import ValidationError
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        _client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        tenant_manager = TenantManager()
        tenant_manager.set_current_tenant(tenant_key)
        accessor = ToolAccessor(db_manager=db_manager, tenant_manager=tenant_manager)

        try:
            with pytest.raises(ValidationError) as exc_info:
                await accessor._project_service.create_project_for_mcp(
                    name="Direct service-layer cross-tenant attempt",
                    description="must be refused below the MCP boundary too",
                    product_id=foreign_id,
                    tenant_key=tenant_key,
                )

            message = str(exc_info.value)
            assert "was not found for this account" in message, message
            assert foreign_id in message, message

            _, projects_here = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert projects_here == 0, "the refused service-layer create must not fall back to the active product"
            _, foreign_projects = await _count_rows_on_product(db_manager, foreign_tenant_key, foreign_id)
            assert foreign_projects == 0, "the refused service-layer create must not write into the other tenant"
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)


# ---------------------------------------------------------------------------
# 5. The response says where it landed -- on BOTH paths
# ---------------------------------------------------------------------------


class TestResponseEchoesTheBinding:
    async def test_create_task_echoes_product_id_and_name_on_the_default_path(self, create_tools_client, db_manager):
        """The default path is the one that misfiled, so it is the one that most
        needs to say where it landed -- an agent can self-check for one field read."""
        client, tenant_key = create_tools_client
        (active_id, active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "echo check", "description": "response must name the product"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_echoes_product_id_and_name_on_the_default_path(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Echo check", "description": "response must name the product"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
        finally:
            await _cleanup(db_manager, tenant_key)
