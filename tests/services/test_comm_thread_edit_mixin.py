# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9289b — operator edit of a thread: rename and settable status.

Two capabilities the operator did not have. A thread could only be named at CREATE
time, which is the top complaint about the Hub; and ``status`` moved only as a side
effect of an agent posting, which is why the operator's list is a wall of stale "Open".

A rename is REFUSED on a project-bound thread: that thread is named after its project
and is kept with the project's 360 memory, so a divergent chat title would misrepresent
the archive. Status carries no such restriction — resolving or closing a project thread
is a normal operator action and says nothing about the project's identity.

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
# Item 1 + 4 — rename, and operator-settable status.
# ---------------------------------------------------------------------------


async def test_rename_a_standalone_thread(db_manager, db_session):
    tenant = _tk("rename")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, subject="  Deploy coordination  ", tenant_key=tenant)

    assert result["subject"] == "Deploy coordination"  # trimmed


async def test_rename_refused_on_a_project_thread(db_manager, db_session):
    """Same rule as delete, same voice — a clean validation error, never a 500."""
    tenant = _tk("renameguard")
    await _seed(db_session, tenant)
    project_id = await _seed_project(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _project_bound(svc, tenant, project_id)

    with pytest.raises(ValidationError) as exc:
        await svc.update_thread(thread_id=tid, subject="my own name", tenant_key=tenant)

    assert "360 memory" in str(exc.value)


async def test_operator_can_set_status_without_an_agent(db_manager, db_session):
    """Item 4: the reason the operator's list is a wall of stale 'Open'."""
    tenant = _tk("status")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, status="resolved", tenant_key=tenant)

    assert result["status"] == "resolved"


async def test_rename_and_status_in_one_call(db_manager, db_session):
    tenant = _tk("both")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    result = await svc.update_thread(thread_id=tid, subject="Renamed", status="closed", tenant_key=tenant)

    assert (result["subject"], result["status"]) == ("Renamed", "closed")


async def test_blank_subject_is_refused(db_manager, db_session):
    """A nameless thread is what this feature exists to fix — do not allow one back in."""
    tenant = _tk("blank")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, subject="   ", tenant_key=tenant)


async def test_empty_update_is_refused(db_manager, db_session):
    """Neither field supplied is a caller mistake, not a silent no-op."""
    tenant = _tk("noop")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, tenant_key=tenant)


async def test_unknown_status_is_refused(db_manager, db_session):
    tenant = _tk("badstatus")
    await _seed(db_session, tenant)
    svc = _service(db_manager, db_session)
    tid = await _standalone(svc, tenant)

    with pytest.raises(ValidationError):
        await svc.update_thread(thread_id=tid, status="banana", tenant_key=tenant)
