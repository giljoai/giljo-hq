# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-6132 regression: generalized soft-delete reaper.

BE-6130b/BE-6137 added soft-delete + a 30-day RECOVER boundary to the
self-service trash/recover entities (CommThread, Task, VisionDocument,
AgentTemplate) but DEFERRED the permanent purge of expired rows. TSK-6132 adds
that reaper: a per-owning-service ``purge_expired_deleted_*`` method that
hard-deletes only the rows trashed longer than ``RECOVER_WINDOW_DAYS`` ago,
driven at startup by ``purge_expired_soft_deleted_entities``.

The load-bearing assertion for every entity is three-way:
  * an EXPIRED soft-deleted row (deleted_at past the window) is hard-deleted;
  * a WITHIN-WINDOW soft-deleted row is LEFT (still recoverable);
  * a LIVE row is LEFT untouched.
Plus FK-safety (children cascade / re-parent correctly) and tenant isolation.

Real DB (rollback-isolated ``db_session``), no mocks — parallel-safe: each test
mints its own tenant key / product, no module-level mutable state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from giljo_mcp.database import tenant_session_context
from giljo_mcp.domain.soft_delete import (
    RECOVER_WINDOW_DAYS,
    recover_window_cutoff,
    recover_window_expired,
)
from giljo_mcp.models import MCPContextIndex, Product, Task, VisionDocument
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.tasks import Message
from giljo_mcp.models.templates import AgentTemplate, TemplateArchive
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.product_vision_service import ProductVisionService
from giljo_mcp.services.task_service import TaskService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.services.template_service import TemplateService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio

# A deleted_at safely past the recovery window, and one safely inside it.
_EXPIRED = datetime.now(UTC) - timedelta(days=RECOVER_WINDOW_DAYS + 1)
_WITHIN = datetime.now(UTC) - timedelta(days=1)


# ===========================================================================
# Shared policy helper
# ===========================================================================


async def test_recover_window_cutoff_matches_per_row_gate():
    """The reaper's discovery cutoff and the per-row recover gate are driven by
    the SAME ``RECOVER_WINDOW_DAYS`` — a row is "expired" iff it is before the
    cutoff, by construction (no drift between purge-eligibility and recover-deny)."""
    now = datetime(2026, 6, 19, 12, 0, 0, tzinfo=UTC)
    cutoff = recover_window_cutoff(now=now)
    assert cutoff == now - timedelta(days=RECOVER_WINDOW_DAYS)

    just_expired = cutoff - timedelta(seconds=1)
    still_recoverable = cutoff + timedelta(seconds=1)
    assert recover_window_expired(just_expired, now=now) is True
    assert recover_window_expired(still_recoverable, now=now) is False


# ===========================================================================
# CommThread reaper
# ===========================================================================


def _cht_service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_taxonomy(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def _trash_thread(svc, db_session, tenant: str, *, subject: str, deleted_at: datetime | None) -> str:
    thread = await svc.create_thread(subject=subject, creator_id="agent-a", tenant_key=tenant)
    tid = thread["thread_id"]
    if deleted_at is not None:
        await svc.delete_thread(thread_id=tid, tenant_key=tenant)
        with tenant_session_context(db_session, tenant):
            await db_session.execute(update(CommThread).where(CommThread.id == tid).values(deleted_at=deleted_at))
            await db_session.flush()
    return tid


async def test_thread_reaper_purges_expired_leaves_within_and_live(db_manager, db_session):
    tenant = f"tk_tsk6132_cht_{uuid4().hex[:6]}"
    await _seed_taxonomy(db_session, tenant)
    svc = _cht_service(db_manager, db_session)

    expired = await _trash_thread(svc, db_session, tenant, subject="expired", deleted_at=_EXPIRED)
    within = await _trash_thread(svc, db_session, tenant, subject="within", deleted_at=_WITHIN)
    live = await _trash_thread(svc, db_session, tenant, subject="live", deleted_at=None)

    purged = await svc.purge_expired_deleted_threads(tenant_key=tenant)
    assert purged == 1

    with tenant_session_context(db_session, tenant):
        remaining = {
            r for (r,) in (await db_session.execute(select(CommThread.id).where(CommThread.tenant_key == tenant)))
        }
    assert expired not in remaining  # expired row reaped
    assert within in remaining  # still-recoverable row left
    assert live in remaining  # live row left

    # Idempotent: a second sweep finds nothing.
    assert await svc.purge_expired_deleted_threads(tenant_key=tenant) == 0


async def test_thread_reaper_cascades_messages(db_manager, db_session):
    """Hard-deleting a trashed thread removes its messages via DB ON DELETE CASCADE."""
    tenant = f"tk_tsk6132_cht_{uuid4().hex[:6]}"
    await _seed_taxonomy(db_session, tenant)
    svc = _cht_service(db_manager, db_session)

    tid = await _trash_thread(svc, db_session, tenant, subject="with-msg", deleted_at=_EXPIRED)
    msg_id = str(uuid4())
    with tenant_session_context(db_session, tenant):
        db_session.add(Message(id=msg_id, tenant_key=tenant, thread_id=tid, content="hello"))
        await db_session.flush()

    await svc.purge_expired_deleted_threads(tenant_key=tenant)

    with tenant_session_context(db_session, tenant):
        msg = (await db_session.execute(select(Message).where(Message.id == msg_id))).scalar_one_or_none()
    assert msg is None  # message cascaded with its trashed thread


async def test_thread_reaper_is_tenant_isolated(db_manager, db_session):
    owner = f"tk_tsk6132_cht_owner_{uuid4().hex[:6]}"
    intruder = f"tk_tsk6132_cht_intr_{uuid4().hex[:6]}"
    await _seed_taxonomy(db_session, owner)
    await _seed_taxonomy(db_session, intruder)
    svc = _cht_service(db_manager, db_session)

    owner_tid = await _trash_thread(svc, db_session, owner, subject="owners-expired", deleted_at=_EXPIRED)

    # The intruder's sweep must not touch the owner's expired thread.
    assert await svc.purge_expired_deleted_threads(tenant_key=intruder) == 0
    owner_trash = await svc.list_deleted_threads(tenant_key=owner)
    assert owner_tid in {t["thread_id"] for t in owner_trash["threads"]}


# ===========================================================================
# Task reaper
# ===========================================================================


@pytest_asyncio.fixture
async def task_product(db_session, test_tenant_key) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"TSK6132 Product {uuid4().hex[:6]}",
        description="reaper task tests",
        tenant_key=test_tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def task_admin(db_session, test_tenant_key) -> User:
    user = User(id=str(uuid4()), tenant_key=test_tenant_key, username=f"admin_{uuid4().hex[:6]}", role="admin")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _trash_task(task_service, db_session, tenant, admin, *, deleted_at: datetime | None) -> str:
    created = await task_service.create_task_for_mcp(
        title=f"task {uuid4().hex[:6]}", description="tsk6132 reaper task", tenant_key=tenant
    )
    task_id = created["task_id"]
    if deleted_at is not None:
        await task_service.delete_task(task_id, str(admin.id))
        await db_session.execute(update(Task).where(Task.id == task_id).values(deleted_at=deleted_at))
        await db_session.flush()
    return task_id


async def test_task_reaper_purges_expired_leaves_within_and_live(
    task_service, db_session, test_tenant_key, task_product, task_admin
):
    expired = await _trash_task(task_service, db_session, test_tenant_key, task_admin, deleted_at=_EXPIRED)
    within = await _trash_task(task_service, db_session, test_tenant_key, task_admin, deleted_at=_WITHIN)
    live = await _trash_task(task_service, db_session, test_tenant_key, task_admin, deleted_at=None)

    purged = await task_service.purge_expired_deleted_tasks(test_tenant_key)
    assert purged == 1

    remaining = {r for (r,) in (await db_session.execute(select(Task.id).where(Task.tenant_key == test_tenant_key)))}
    assert expired not in remaining
    assert within in remaining
    assert live in remaining

    assert await task_service.purge_expired_deleted_tasks(test_tenant_key) == 0


async def test_task_reaper_reparents_live_subtask(task_service, db_session, test_tenant_key, task_product, task_admin):
    """A live child subtask of an expired-trashed parent is re-parented to NULL
    (the self-FK has no cascade) — FK-safe and the child survives."""
    parent = await _trash_task(task_service, db_session, test_tenant_key, task_admin, deleted_at=_EXPIRED)
    child = await _trash_task(task_service, db_session, test_tenant_key, task_admin, deleted_at=None)
    await db_session.execute(update(Task).where(Task.id == child).values(parent_task_id=parent))
    await db_session.flush()

    await task_service.purge_expired_deleted_tasks(test_tenant_key)

    surviving = (await db_session.execute(select(Task).where(Task.id == child))).scalar_one_or_none()
    assert surviving is not None  # child survived
    assert surviving.parent_task_id is None  # re-parented off the reaped parent
    gone = (await db_session.execute(select(Task).where(Task.id == parent))).scalar_one_or_none()
    assert gone is None


async def test_task_reaper_is_tenant_isolated(
    task_service, db_manager, db_session, test_tenant_key, task_product, task_admin
):
    expired = await _trash_task(task_service, db_session, test_tenant_key, task_admin, deleted_at=_EXPIRED)

    other_tenant = TenantManager.generate_tenant_key()
    other_tm = MagicMock()
    other_tm.get_current_tenant.return_value = other_tenant
    other_service = TaskService(db_manager=db_manager, tenant_manager=other_tm, session=db_session)
    assert await other_service.purge_expired_deleted_tasks(other_tenant) == 0

    still_there = (await db_session.execute(select(Task.id).where(Task.id == expired))).scalar_one_or_none()
    assert still_there == expired


# ===========================================================================
# VisionDocument reaper
# ===========================================================================


async def _make_product(db_session, tenant: str) -> Product:
    product = Product(
        id=str(uuid4()),
        name=f"VD Product {uuid4().hex[:6]}",
        description="reaper vision tests",
        tenant_key=tenant,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _make_trashed_doc(db_session, tenant, product_id, *, deleted_at: datetime | None) -> tuple[str, str]:
    doc = VisionDocument(
        id=str(uuid4()),
        tenant_key=tenant,
        product_id=product_id,
        document_name=f"Vision {uuid4().hex[:6]}",
        document_type="vision",
        vision_document="alpha beta gamma vision body",
        storage_type="inline",
        content_hash="hash" + uuid4().hex[:8],
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=True,
        chunk_count=1,
        deleted_at=deleted_at,
    )
    db_session.add(doc)
    await db_session.flush()
    chunk = MCPContextIndex(
        tenant_key=tenant,
        product_id=product_id,
        vision_document_id=doc.id,
        content="alpha beta gamma chunk body",
        keywords=["beta"],
        chunk_order=0,
    )
    db_session.add(chunk)
    await db_session.flush()
    return doc.id, chunk.id


async def test_vision_reaper_purges_expired_leaves_within_and_live(db_manager, db_session):
    tenant = f"tk_tsk6132_vd_{uuid4().hex[:6]}"
    svc = ProductVisionService(db_manager=db_manager, tenant_key=tenant, test_session=db_session)
    with tenant_session_context(db_session, tenant):
        product = await _make_product(db_session, tenant)
        expired, _ = await _make_trashed_doc(db_session, tenant, product.id, deleted_at=_EXPIRED)
        within, _ = await _make_trashed_doc(db_session, tenant, product.id, deleted_at=_WITHIN)
        live, _ = await _make_trashed_doc(db_session, tenant, product.id, deleted_at=None)

    purged = await svc.purge_expired_deleted_documents()
    assert purged == 1

    with tenant_session_context(db_session, tenant):
        remaining = {
            r
            for (r,) in (await db_session.execute(select(VisionDocument.id).where(VisionDocument.tenant_key == tenant)))
        }
        # Chunk of the reaped doc cascades at the DB level.
        chunk_count = (
            await db_session.execute(
                select(func.count()).select_from(MCPContextIndex).where(MCPContextIndex.vision_document_id == expired)
            )
        ).scalar_one()
    assert expired not in remaining
    assert within in remaining
    assert live in remaining
    assert chunk_count == 0  # RAG chunks cascaded with the reaped doc

    assert await svc.purge_expired_deleted_documents() == 0


async def test_vision_reaper_is_tenant_isolated(db_manager, db_session):
    owner = f"tk_tsk6132_vd_owner_{uuid4().hex[:6]}"
    intruder = f"tk_tsk6132_vd_intr_{uuid4().hex[:6]}"
    with tenant_session_context(db_session, owner):
        owner_product = await _make_product(db_session, owner)
        owner_doc, _ = await _make_trashed_doc(db_session, owner, owner_product.id, deleted_at=_EXPIRED)

    intruder_svc = ProductVisionService(db_manager=db_manager, tenant_key=intruder, test_session=db_session)
    assert await intruder_svc.purge_expired_deleted_documents() == 0

    with tenant_session_context(db_session, owner):
        still_there = (
            await db_session.execute(select(VisionDocument.id).where(VisionDocument.id == owner_doc))
        ).scalar_one_or_none()
    assert still_there == owner_doc


# ===========================================================================
# AgentTemplate reaper
# ===========================================================================


def _tpl_service(db_manager, tenant_key, db_session) -> TemplateService:
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return TemplateService(db_manager=db_manager, tenant_manager=mock_tm, session=db_session)


async def _make_trashed_template(db_session, tenant, *, deleted_at: datetime | None, with_archive: bool = False) -> str:
    tpl = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant,
        name=f"tsk6132-tpl-{uuid4().hex[:8]}",
        role="custom",
        category="custom",
        system_instructions="# Test\nReaper template.",
        is_active=True,
        version="1.0.0",
        deleted_at=deleted_at,
    )
    db_session.add(tpl)
    await db_session.flush()
    if with_archive:
        db_session.add(
            TemplateArchive(
                id=str(uuid4()),
                tenant_key=tenant,
                template_id=tpl.id,
                name=tpl.name,
                category=tpl.category,
                version="0.9.0",
                system_instructions="# old\nPrevious version.",
                archive_reason="pre-reap snapshot",
                archive_type="manual",
            )
        )
        await db_session.flush()
    return tpl.id


async def test_template_reaper_purges_expired_leaves_within_and_live(db_manager, db_session, test_tenant_key):
    svc = _tpl_service(db_manager, test_tenant_key, db_session)
    expired = await _make_trashed_template(db_session, test_tenant_key, deleted_at=_EXPIRED)
    within = await _make_trashed_template(db_session, test_tenant_key, deleted_at=_WITHIN)
    live = await _make_trashed_template(db_session, test_tenant_key, deleted_at=None)

    purged = await svc.purge_expired_deleted_templates(test_tenant_key)
    assert purged == 1

    remaining = {
        r
        for (r,) in (
            await db_session.execute(select(AgentTemplate.id).where(AgentTemplate.tenant_key == test_tenant_key))
        )
    }
    assert expired not in remaining
    assert within in remaining
    assert live in remaining

    assert await svc.purge_expired_deleted_templates(test_tenant_key) == 0


async def test_template_reaper_deletes_archives(db_manager, db_session, test_tenant_key):
    """Reaping a trashed template removes its TemplateArchive version history
    (mirrors hard_delete_template; archives have no DB cascade)."""
    svc = _tpl_service(db_manager, test_tenant_key, db_session)
    tpl_id = await _make_trashed_template(db_session, test_tenant_key, deleted_at=_EXPIRED, with_archive=True)

    await svc.purge_expired_deleted_templates(test_tenant_key)

    archive_count = (
        await db_session.execute(
            select(func.count()).select_from(TemplateArchive).where(TemplateArchive.template_id == tpl_id)
        )
    ).scalar_one()
    assert archive_count == 0


async def test_template_reaper_is_tenant_isolated(db_manager, db_session, test_tenant_key):
    expired = await _make_trashed_template(db_session, test_tenant_key, deleted_at=_EXPIRED)

    other_tenant = TenantManager.generate_tenant_key()
    other_svc = _tpl_service(db_manager, other_tenant, db_session)
    assert await other_svc.purge_expired_deleted_templates(other_tenant) == 0

    still_there = (
        await db_session.execute(select(AgentTemplate.id).where(AgentTemplate.id == expired))
    ).scalar_one_or_none()
    assert still_there == expired


# ---------------------------------------------------------------------------
# BE-9289b: the soft-delete lifecycle moved to CommThreadSoftDeleteMixin. The move was
# a pure relocation, so the behavioural coverage above is unchanged — this pins the
# COMPOSITION, which is the one thing a relocation can silently break: if the mixin is
# ever dropped from the service's bases, every test above would fail with an obscure
# AttributeError instead of naming the cause.
# ---------------------------------------------------------------------------


def test_soft_delete_lifecycle_is_served_by_the_mixin():
    from giljo_mcp.services._comm_thread_softdelete_mixin import CommThreadSoftDeleteMixin
    from giljo_mcp.services.comm_thread_service import CommThreadService

    assert issubclass(CommThreadService, CommThreadSoftDeleteMixin)
    for name in ("delete_thread", "restore_thread", "list_deleted_threads", "purge_expired_deleted_threads"):
        assert hasattr(CommThreadService, name), f"{name} vanished from the service API"
        # Served BY the mixin, not redefined on the service — that is what makes the
        # extraction a single source of truth rather than a copy.
        assert getattr(CommThreadService, name) is getattr(CommThreadSoftDeleteMixin, name)
