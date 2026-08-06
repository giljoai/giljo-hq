# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9157 — ``superseded`` project status + successor linking.

Coverage:
  * ``refuse_if_superseded`` — the shared 360-write refusal helper.
  * ``list_projects_for_mcp`` default-visibility CHARACTERIZATION (museum rule:
    pin current behavior first) + the new ``include_superseded`` filter.
  * ``ProjectService.update_project`` successor-pointer validation (within-tenant,
    no self-supersession) + successful persistence.
  * MCP-BOUNDARY refusal (through the real @mcp.tool transport, BE-5042 lesson):
    a 360 write to a superseded project returns the structured PROJECT_SUPERSEDED
    rejection as normal content (Tier-2), not an isError.

Parallel-safe: fresh tenant_key per test; DB-backed tests use the rolled-back
db_session (TransactionalTestContext); no module-level mutable state.
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from mcp.shared.memory import create_connected_server_and_client_session

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.tools._memory_helpers import refuse_if_superseded


_PRODUCT_SERVICE_PATH = "giljo_mcp.services.product_service.ProductService"


# ===========================================================================
# refuse_if_superseded — pure helper
# ===========================================================================


def _fake_project(status: str, project_id: str = "proj-1", successor: str | None = None):
    return SimpleNamespace(id=project_id, status=status, successor_project_id=successor)


def test_refuse_helper_returns_rejection_for_superseded():
    rejection = refuse_if_superseded(_fake_project("superseded", successor="succ-9"))
    assert rejection is not None
    assert rejection["success"] is False
    assert rejection["error"] == "PROJECT_SUPERSEDED"
    assert rejection["project_id"] == "proj-1"
    assert rejection["successor_project_id"] == "succ-9"


@pytest.mark.parametrize("status", ["active", "inactive", "completed", "cancelled"])
def test_refuse_helper_passes_through_non_superseded(status):
    assert refuse_if_superseded(_fake_project(status)) is None


def test_refuse_helper_handles_none_project():
    assert refuse_if_superseded(None) is None


# ===========================================================================
# list_projects_for_mcp — default visibility + include_superseded
# ===========================================================================


def _make_accessor(tenant_key: str = "tenant-be9157"):
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    db_manager = Mock()
    mock_session = AsyncMock()
    db_manager.get_session_async = Mock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.info = {}  # tenant_session_context save/restore target
    tenant_manager = Mock()
    tenant_manager.get_current_tenant = Mock(return_value=tenant_key)
    return ToolAccessor(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
        test_session=mock_session,
    )


def _list_item(project_id: str, status: str):
    """Minimal ProjectListItem-shaped mock for the post-fetch filter + projection."""
    return SimpleNamespace(
        id=project_id,
        name=f"P-{project_id}",
        status=status,
        hidden=False,
        project_type=None,
        taxonomy_alias=None,
        created_at="2026-07-13T00:00:00",
        completed_at=None,
        description="",
        mission="",
    )


async def _run_list(accessor, repo_rows, **kwargs):
    """Drive list_projects_for_mcp with a patched repo + projection; capture the
    ``status`` argument the repo received so the SQL-side default can be asserted.
    Returns (result, captured_status_arg)."""
    svc = accessor._project_service
    captured: dict[str, Any] = {}

    async def _fake_list_projects(**kw):
        captured["status"] = kw.get("status")
        return repo_rows

    async def _fake_build(filtered, *a, **kw):
        return [{"project_id": p.id, "status": p.status} for p in filtered]

    mock_product = Mock()
    mock_product.id = "prod-1"

    with (
        patch.object(svc, "list_projects", new=AsyncMock(side_effect=_fake_list_projects)),
        patch.object(svc, "_build_mcp_project_list", new=AsyncMock(side_effect=_fake_build)),
        patch.object(svc, "_get_valid_project_types", new=AsyncMock(return_value=[])),
        patch(_PRODUCT_SERVICE_PATH) as mock_ps,
    ):
        mock_ps.return_value.get_active_product = AsyncMock(return_value=mock_product)
        result = await svc.list_projects_for_mcp(tenant_key="tenant-be9157", **kwargs)
    return result, captured["status"]


@pytest.mark.asyncio
async def test_characterization_default_excludes_lifecycle_finished_at_sql():
    """MUSEUM CHARACTERIZATION: with no filters, the default agent view pushes a
    status set to SQL that INCLUDES active/inactive and EXCLUDES the
    lifecycle-finished states (completed/cancelled/terminated/deleted) AND the new
    superseded value. This pins the default visibility agents depend on."""
    accessor = _make_accessor()
    _result, status_arg = await _run_list(accessor, [_list_item("a", "active")])

    assert isinstance(status_arg, list)
    assert "active" in status_arg and "inactive" in status_arg
    for hidden_status in ("completed", "cancelled", "terminated", "deleted", "superseded"):
        assert hidden_status not in status_arg, f"{hidden_status} must not be in the default SQL status set"


@pytest.mark.asyncio
async def test_superseded_excluded_by_default_post_fetch():
    """Even if a superseded row reaches the post-fetch stage, it is dropped by default."""
    accessor = _make_accessor()
    rows = [_list_item("a", "active"), _list_item("s", "superseded")]
    result, _ = await _run_list(accessor, rows)
    ids = {p["project_id"] for p in result["projects"]}
    assert ids == {"a"}, f"superseded must be hidden by default, got {ids}"


@pytest.mark.asyncio
async def test_superseded_hidden_even_with_include_completed():
    """include_completed surfaces completed/cancelled but NOT superseded (own gate)."""
    accessor = _make_accessor()
    rows = [_list_item("c", "completed"), _list_item("s", "superseded")]
    result, _ = await _run_list(accessor, rows, include_completed=True)
    ids = {p["project_id"] for p in result["projects"]}
    assert "s" not in ids, f"superseded must stay hidden under include_completed, got {ids}"
    assert "c" in ids


@pytest.mark.asyncio
async def test_include_superseded_true_surfaces_superseded():
    accessor = _make_accessor()
    rows = [_list_item("a", "active"), _list_item("s", "superseded")]
    result, _ = await _run_list(accessor, rows, include_superseded=True)
    ids = {p["project_id"] for p in result["projects"]}
    assert ids == {"a", "s"}, f"include_superseded=True must surface superseded, got {ids}"


@pytest.mark.asyncio
async def test_explicit_status_superseded_overrides_default_exclusion():
    """An explicit status='superseded' request wins over the default exclusion."""
    accessor = _make_accessor()
    rows = [_list_item("s", "superseded")]
    result, status_arg = await _run_list(accessor, rows, status="superseded")
    ids = {p["project_id"] for p in result["projects"]}
    assert ids == {"s"}, f"explicit status=superseded must surface it, got {ids}"
    # And it was pushed to SQL as the explicit filter.
    assert status_arg == "superseded"


# ===========================================================================
# ProjectService.update_project — successor pointer validation + persistence
# ===========================================================================


@pytest_asyncio.fixture
async def superseding_setup(db_manager, db_session):
    """Two committed-in-transaction projects under one tenant, plus a service
    bound to the rolled-back session with tenant context set."""
    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project
    from giljo_mcp.services.project_service import ProjectService
    from giljo_mcp.tenant import TenantManager, current_tenant

    tenant_key = TenantManager.generate_tenant_key()
    suffix = tenant_key[:8]

    product = Product(
        id=f"be9157-prod-{suffix}",
        name=f"BE9157 Product {suffix}",
        description="BE-9157",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    def _proj(pid, name):
        return Project(
            id=pid,
            tenant_key=tenant_key,
            product_id=product.id,
            name=name,
            description="d",
            mission="m",
            status="inactive",
            series_number=random.randint(1, 9000),
        )

    victim = _proj(f"be9157-victim-{suffix}", "Victim")
    successor = _proj(f"be9157-succ-{suffix}", "Successor")
    db_session.add_all([victim, successor])
    await db_session.flush()

    manager = TenantManager()
    manager.set_current_tenant(tenant_key)
    token = current_tenant.set(tenant_key)
    svc = ProjectService(db_manager=db_manager, tenant_manager=manager, test_session=db_session)
    try:
        yield svc, victim, successor, tenant_key
    finally:
        current_tenant.reset(token)


@pytest.mark.asyncio
async def test_update_persists_superseded_status_and_successor(superseding_setup):
    svc, victim, successor, _tk = superseding_setup
    result = await svc.update_project(
        project_id=victim.id,
        updates={"status": "superseded", "successor_project_id": successor.id},
    )
    assert result.status == ProjectStatus.SUPERSEDED
    assert result.successor_project_id == successor.id


@pytest.mark.asyncio
async def test_update_supersede_allowed_from_completed_immutable_status(superseding_setup):
    """A COMPLETED (immutable) project can still be marked superseded — the
    supersede lifecycle transition is carved out of the immutable-write guard,
    because replacing already-shipped work is the primary use case."""
    svc, victim, successor, _tk = superseding_setup
    # Move the victim into the immutable COMPLETED state first (direct set, then
    # the supersede transition must still be permitted from there).
    victim.status = ProjectStatus.COMPLETED
    await svc._test_session.flush()

    result = await svc.update_project(
        project_id=victim.id,
        updates={"status": "superseded", "successor_project_id": successor.id},
    )
    assert result.status == ProjectStatus.SUPERSEDED
    assert result.successor_project_id == successor.id


@pytest.mark.asyncio
async def test_update_rejects_self_supersession(superseding_setup):
    svc, victim, _successor, _tk = superseding_setup
    with pytest.raises(ValidationError) as exc:
        await svc.update_project(
            project_id=victim.id,
            updates={"status": "superseded", "successor_project_id": victim.id},
        )
    assert "supersede itself" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_update_rejects_unknown_successor(superseding_setup):
    svc, victim, _successor, _tk = superseding_setup
    with pytest.raises(ValidationError) as exc:
        await svc.update_project(
            project_id=victim.id,
            updates={"status": "superseded", "successor_project_id": "does-not-exist"},
        )
    assert "successor" in str(exc.value).lower()


# ===========================================================================
# MCP-BOUNDARY refusal (through the real @mcp.tool transport — BE-5042 lesson)
# ===========================================================================


def _content_text(result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in (result.content or []))


@pytest_asyncio.fixture
async def superseded_tool_client(db_manager, db_session, monkeypatch):
    """Wire the real ToolAccessor (rolled-back session) into the in-memory MCP
    transport and seed a SUPERSEDED project. Yields (client, tenant_key, project_id)."""
    from api import app_state
    from api.endpoints.mcp_sdk_server import mcp
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.models.organizations import Organization
    from giljo_mcp.models.products import Product
    from giljo_mcp.models.projects import Project
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.tool_accessor import ToolAccessor
    from giljo_mcp.tools.write_memory_entry import write_360_memory

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = tenant_key[:8]

    org = Organization(name=f"BE9157 Org {suffix}", slug=f"be9157-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=f"be9157b-prod-{suffix}",
        name=f"BE9157 Product {suffix}",
        description="BE-9157 boundary",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=f"be9157b-proj-{suffix}",
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE9157 Superseded {suffix}",
        description="BE-9157",
        mission="superseded",
        status="superseded",
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    async def _write_with_session(tenant_key: str, **kwargs: Any) -> dict[str, Any]:
        return await write_360_memory(tenant_key=tenant_key, session=db_session, db_manager=db_manager, **kwargs)

    accessor.write_memory_entry = _write_with_session
    state.tool_accessor = accessor
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, project.id
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


@pytest.mark.asyncio
async def test_mcp_boundary_write_to_superseded_is_tier2_rejection(superseded_tool_client):
    """A 360 write to a superseded project returns PROJECT_SUPERSEDED as normal
    content (Tier-2), NOT an isError — the agent can self-correct to the successor."""
    client, _tenant_key, project_id = superseded_tool_client

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "write_memory_entry",
            {
                "project_id": project_id,
                "summary": "Attempting to write to a superseded project",
                "key_outcomes": ["should be refused"],
                "decisions_made": ["superseded projects are read-only for closeout"],
                "entry_type": "baseline",
                "author_job_id": "",
            },
        )

    assert not result.isError, f"PROJECT_SUPERSEDED must be Tier-2 content, not isError: {_content_text(result)!r}"
    parsed = json.loads(_content_text(result))
    assert parsed.get("success") is False
    assert parsed.get("error") == "PROJECT_SUPERSEDED", f"got: {parsed!r}"
