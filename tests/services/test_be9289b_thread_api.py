# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9289b — the project-bound delete guard that was specified but never implemented.

``ThreadList.vue`` carries a comment asserting a project-bound thread is "non-deletable
while the project lives (§2.5 guard)" and simply hides the delete button. Nothing in the
service, the repository or the REST route ever enforced it. A hidden button is not a
guard: any other client, or a stale tab, could delete a project's chat log. Left
unrestored, the 30-day reaper (``purge_expired_deleted_threads``) then hard-deletes the
row and the whole message subtree goes with it via ``ON DELETE CASCADE`` — so the loss
is delayed and silent rather than immediate.

The guard is enforced at the SERVICE so every caller inherits it, which is the point:
the entire failure mode was enforcement living in one client. Status is deliberately NOT
restricted, and restore is deliberately unguarded.

Parallel-safe: real DB via the rollback-isolated ``db_session`` fixture, no module-level
mutable state, each test owns its setup, every query is tenant-scoped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9289b_{suffix}_{uuid.uuid4().hex[:8]}"


def _service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _seed_project(db_session, tenant: str) -> str:
    with tenant_session_context(db_session, tenant):
        # BE-9437: a project belongs to a product. Its own, so an active
        # seed cannot collide under idx_project_single_active_per_product.
        _owning_product_project = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant,
            name=f"Owning Product {uuid.uuid4().hex[:6]}",
            description="seeded",
            is_active=False,
        )
        db_session.add(_owning_product_project)
        project = Project(
            id=str(uuid.uuid4()),
            name=f"BE-9289b {uuid.uuid4().hex[:6]}",
            description="thread api test project",
            mission="exercise thread edit",
            status="active",
            tenant_key=tenant,
            product_id=_owning_product_project.id,
            series_number=1,
            execution_mode="claude_code_cli",
            created_at=datetime.now(UTC),
            implementation_launched_at=datetime.now(UTC),
        )
        db_session.add(project)
        await db_session.flush()
    return project.id


async def _standalone(svc, tenant: str) -> str:
    thread = await svc.create_thread(subject="standalone", creator_id="agent-a", tenant_key=tenant)
    return thread["thread_id"]


async def _project_bound(svc, tenant: str, project_id: str) -> str:
    thread = await svc.create_thread(subject="bound", creator_id="agent-a", project_id=project_id, tenant_key=tenant)
    return thread["thread_id"]


# ---------------------------------------------------------------------------
# The unimplemented §2.5 guard — delete refused on a project-bound thread.
# ---------------------------------------------------------------------------


async def test_project_bound_thread_cannot_be_deleted(db_manager, db_session):
    """FAIL-FIRST: today a project thread deletes like any other.

    The UI hides the button and a comment claims the invariant, but nothing enforces
    it. This is the enforcement, at the service so every caller inherits it.
    """
    tenant = _tk("delguard")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _project_bound(svc, tenant, project_id)

    with pytest.raises(ValidationError) as exc:
        await svc.delete_thread(thread_id=tid, tenant_key=tenant)

    # Readable, and it says WHY — never a bare 500 or a silent no-op.
    assert "360 memory" in str(exc.value)


async def test_standalone_thread_still_deletes(db_manager, db_session):
    """The guard must be narrow: an ordinary thread is still deletable."""
    tenant = _tk("delok")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.delete_thread(thread_id=tid, tenant_key=tenant)

    assert result["deleted"] is True


async def test_project_thread_can_still_be_closed(db_manager, db_session):
    """Condition 5: the guard must NOT leak into status. Resolving or closing a
    project thread is a normal operator action and says nothing about identity."""
    tenant = _tk("closeok")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _project_bound(svc, tenant, project_id)

    result = await svc.update_thread(thread_id=tid, status="closed", tenant_key=tenant)

    assert result["status"] == "closed"


async def test_restore_is_not_guarded(db_manager, db_session):
    """Condition 6: restoring is always safe, including for a thread trashed before
    the guard existed — that is the recovery path for legacy rows."""
    tenant = _tk("restore")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)
    await svc.delete_thread(thread_id=tid, tenant_key=tenant)

    restored = await svc.restore_thread(thread_id=tid, tenant_key=tenant)

    assert restored["thread_id"] == tid
