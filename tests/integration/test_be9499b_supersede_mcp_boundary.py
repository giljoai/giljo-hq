# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9499b -- the supersede door, MCP-transport boundary.

Operator ruling 2026-08-26 (see project BE-9499b): an agent should be able to
mark a project superseded over MCP, but `superseded` is meaningless without a
`successor_project_id` -- a null-successor row is an audit-trail dead end
(`_memory_helpers.refuse_if_superseded` hands agents that pointer as the
remedy for hitting a superseded project, which only works if it's always
populated).

This file pins, at the real `@mcp.tool` transport:
  1. A supersede with NO successor is refused as a structured Tier-2
     rejection (SUPERSEDE_REQUIRES_SUCCESSOR), never a 500, never a partial
     write -- reproduced FAILING first (pre-fix this raised ValidationError
     for a completely different reason: `superseded` wasn't even in
     VALID_UPDATE_STATUSES).
  2. A supersede with an INELIGIBLE successor (cancelled/terminated/deleted/
     superseded) is refused the SAME way.
  3. A supersede with a valid successor (active/completed/inactive) succeeds
     end-to-end, the successor pointer lands on the row, and REST PATCH
     (`ProjectService.update_project`, the same owning writer) behaves
     byte-identically.
  4. `is_immutable` is unweakened: once superseded, a further plain write is
     still refused.

Parallel-safe: each test generates a fresh tenant_key + cleans up its own rows.
"""

from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


@pytest_asyncio.fixture
async def supersede_client(db_manager, monkeypatch):
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


def _project(project_id: str, tenant_key: str, product_id: str, *, name: str, status: str) -> Project:
    return Project(
        id=project_id,
        tenant_key=tenant_key,
        product_id=product_id,
        name=name,
        description="BE-9499b supersede boundary test",
        mission="test mission",
        status=status,
        series_number=random.randint(1, 9999),
    )


async def _seed(db_manager, tenant_key: str, *, predecessor_status="inactive", successor_status="inactive"):
    product_id = str(uuid4())
    predecessor_id = str(uuid4())
    successor_id = str(uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE9499b Supersede Product {uuid4().hex[:6]}",
                description="BE-9499b supersede boundary test",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(_project(predecessor_id, tenant_key, product_id, name="Predecessor", status=predecessor_status))
        session.add(_project(successor_id, tenant_key, product_id, name="Successor", status=successor_status))
        await session.commit()
    return product_id, predecessor_id, successor_id


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


class TestSupersedeRefusals:
    async def test_supersede_with_no_successor_is_refused_structured(self, supersede_client, db_manager):
        client, tenant_key = supersede_client
        _product_id, predecessor_id, _successor_id = await _seed(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project", {"project_id": predecessor_id, "status": "superseded"}
                )

            assert not result.is_error, (
                f"missing successor must be a structured Tier-2 rejection, not isError: {result.content!r}"
            )
            payload = _payload(result)
            assert payload.get("success") is False
            assert payload.get("error") == "SUPERSEDE_REQUIRES_SUCCESSOR"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                predecessor = (await verify.execute(select(Project).where(Project.id == predecessor_id))).scalar_one()
            assert predecessor.status == "inactive", "must not partially write status without a successor"
            assert predecessor.successor_project_id is None
        finally:
            await _cleanup(db_manager, tenant_key)

    @pytest.mark.parametrize("ineligible_status", ["cancelled", "terminated", "deleted", "superseded"])
    async def test_supersede_with_ineligible_successor_is_refused_structured(
        self, supersede_client, db_manager, ineligible_status
    ):
        client, tenant_key = supersede_client
        _product_id, predecessor_id, successor_id = await _seed(
            db_manager, tenant_key, successor_status=ineligible_status
        )

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project",
                    {
                        "project_id": predecessor_id,
                        "status": "superseded",
                        "successor_project_id": successor_id,
                    },
                )

            assert not result.is_error, (
                f"ineligible successor ({ineligible_status}) must be structured, not isError: {result.content!r}"
            )
            payload = _payload(result)
            assert payload.get("success") is False
            assert payload.get("error") == "SUPERSEDE_REQUIRES_SUCCESSOR"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                predecessor = (await verify.execute(select(Project).where(Project.id == predecessor_id))).scalar_one()
            assert predecessor.status == "inactive", "must not partially write with an ineligible successor"
        finally:
            await _cleanup(db_manager, tenant_key)


class TestSupersedeHappyPath:
    @pytest.mark.parametrize("eligible_status", ["active", "completed", "inactive"])
    async def test_supersede_with_eligible_successor_succeeds(self, supersede_client, db_manager, eligible_status):
        client, tenant_key = supersede_client
        _product_id, predecessor_id, successor_id = await _seed(
            db_manager, tenant_key, successor_status=eligible_status
        )

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project",
                    {
                        "project_id": predecessor_id,
                        "status": "superseded",
                        "successor_project_id": successor_id,
                    },
                )

            assert not result.is_error, f"eligible-successor supersede must succeed: {result.content!r}"
            payload = _payload(result)
            assert payload.get("success") is True
            assert payload.get("status") == "superseded"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                predecessor = (await verify.execute(select(Project).where(Project.id == predecessor_id))).scalar_one()
            assert predecessor.status == "superseded"
            assert predecessor.successor_project_id == successor_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_further_write_after_supersede_still_refused(self, supersede_client, db_manager):
        """is_immutable is unweakened: reachable FROM mcp != writable AFTER."""
        client, tenant_key = supersede_client
        _product_id, predecessor_id, successor_id = await _seed(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                first = await mcp_session.call_tool(
                    "update_project",
                    {
                        "project_id": predecessor_id,
                        "status": "superseded",
                        "successor_project_id": successor_id,
                    },
                )
                assert not first.is_error
                assert _payload(first).get("success") is True

                second = await mcp_session.call_tool(
                    "update_project", {"project_id": predecessor_id, "name": "Renamed after supersede"}
                )
            assert second.is_error, "a superseded project must still refuse an ordinary metadata write"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_rest_door_matches_mcp_door_byte_identical(self, db_manager):
        """REST PATCH (ProjectService.update_project) and the MCP tool both call
        the SAME owning writer -- pin that the REST door's behaviour did not
        move under this change (ruling 1: one writer, both doors agree).
        """
        tenant_key = TenantManager.generate_tenant_key()
        tenant_manager = TenantManager()
        tenant_manager.set_current_tenant(tenant_key)
        _product_id, predecessor_id, successor_id = await _seed(db_manager, tenant_key)

        service = ProjectService(db_manager=db_manager, tenant_manager=tenant_manager)
        try:
            # No successor -> SUPERSEDE_REQUIRES_SUCCESSOR, raised (REST's
            # generic PATCH endpoint lets ProjectService exceptions propagate to
            # its own error-mapping layer -- unlike the MCP adapter's Tier-2
            # catch, this door was never given a structured-return carve-out).
            from giljo_mcp.exceptions import ValidationError

            with pytest.raises(ValidationError) as exc_info:
                await service.update_project(project_id=predecessor_id, updates={"status": "superseded"})
            assert exc_info.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"

            # Eligible successor -> succeeds, same as the MCP door.
            updated = await service.update_project(
                project_id=predecessor_id,
                updates={"status": "superseded", "successor_project_id": successor_id},
            )
            assert updated.status == "superseded"
            assert updated.successor_project_id == successor_id
        finally:
            await _cleanup(db_manager, tenant_key)
