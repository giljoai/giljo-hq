# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6054a repo-layer regression — Agent Message Hub data foundation.

Real DB (rollback-isolated ``db_session``), no mocks. Covers the failing layer
for link a:

- create a thread, mint a ``CHT-####`` serial, attach a message via ``thread_id``,
  query a standalone (project-less) thread;
- the FORWARD-hazard guard: a NULL-``project_id`` chat message must NOT break a
  project-scoped message reader (the equality filter excludes it by design) and
  must still be reachable by its ``thread_id``;
- CHT type missing -> a clean ValidationError (the documented 422), not a serial;
- collision-safe participant join;
- tenant isolation on every read.

Each test establishes tenant context with ``tenant_session_context`` exactly as
the MCP tool boundary (BE-6054b) will — the repository itself is intentionally
tenant-context-agnostic, like every other repository.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Message, Product, Project
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be6054a_{suffix}"


async def test_create_thread_mints_sequential_cht_serial(db_session):
    tenant = _tk("mint")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        t1 = await repo.create_thread(db_session, tenant, subject="first")
        t2 = await repo.create_thread(db_session, tenant, subject="second")

    assert t1.serial == 1
    assert t1.taxonomy_alias == "CHT-0001"
    assert t2.serial == 2
    assert t2.taxonomy_alias == "CHT-0002"
    # Standalone by default: no product / project anchor.
    assert t1.product_id is None
    assert t1.project_id is None
    assert t1.status == "open"


async def test_create_thread_without_cht_type_raises_422(db_session):
    """A tenant lacking the CHT taxonomy type (backfill not applied) gets a clear
    ValidationError, never a confusing orphan serial."""
    tenant = _tk("no_cht")  # deliberately NOT seeded
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant), pytest.raises(ValidationError) as exc:
        await repo.create_thread(db_session, tenant, subject="should fail")
    assert "CHT" in str(exc.value)


async def test_attach_standalone_message_and_query_by_thread(db_session):
    tenant = _tk("attach")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        thread = await repo.create_thread(db_session, tenant, subject="standalone chat")
        # A standalone chat message: thread_id set, project_id NULL.
        msg = Message(tenant_key=tenant, thread_id=thread.id, project_id=None, content="hello board")
        db_session.add(msg)
        await db_session.flush()

        rows = (
            (
                await db_session.execute(
                    select(Message).where(Message.tenant_key == tenant, Message.thread_id == thread.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].project_id is None
        assert rows[0].content == "hello board"

        # The thread itself is queryable as a standalone (project_id IS NULL) thread.
        standalone = await repo.list_threads(db_session, tenant, project_id=None)
    assert thread.id in {t.id for t in standalone}


async def test_null_project_id_message_does_not_break_project_scoped_reader(db_session):
    """FORWARD-hazard guard: a project-scoped equality reader returns ONLY the
    project-anchored message and silently excludes the NULL chat message — and
    the NULL message remains reachable via its thread anchor (not lost)."""
    tenant = _tk("guard")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        # BE-9437: a project belongs to a product.
        product = Product(tenant_key=tenant, name="P product", description="d", is_active=False)
        db_session.add(product)
        await db_session.flush()
        project = Project(tenant_key=tenant, product_id=product.id, name="P", description="d", mission="m")
        db_session.add(project)
        await db_session.flush()

        thread = await repo.create_thread(db_session, tenant, subject="mixed")
        project_msg = Message(tenant_key=tenant, project_id=project.id, content="project chatter")
        standalone_msg = Message(tenant_key=tenant, thread_id=thread.id, project_id=None, content="board chatter")
        db_session.add_all([project_msg, standalone_msg])
        await db_session.flush()

        # The exact equality-filter shape every project-scoped reader uses (audit:
        # "filter naturally excludes null, intended"). Must NOT raise and must NOT
        # surface the NULL row.
        project_scoped = (
            (
                await db_session.execute(
                    select(Message).where(Message.tenant_key == tenant, Message.project_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        assert {m.id for m in project_scoped} == {project_msg.id}
        assert standalone_msg.id not in {m.id for m in project_scoped}

        # The NULL chat message is not lost — it is reachable by its thread anchor.
        by_thread = (
            (
                await db_session.execute(
                    select(Message).where(Message.tenant_key == tenant, Message.thread_id == thread.id)
                )
            )
            .scalars()
            .all()
        )
        assert {m.id for m in by_thread} == {standalone_msg.id}


async def test_add_participant_is_collision_safe(db_session):
    tenant = _tk("participant")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        thread = await repo.create_thread(db_session, tenant, subject="roster")

        p1 = await repo.add_participant(
            db_session, tenant, thread.id, participant_id="agent-x", participant_type="agent", display_name="X"
        )
        # Re-joining the same identity is idempotent — same row, no duplicate.
        p2 = await repo.add_participant(
            db_session, tenant, thread.id, participant_id="agent-x", participant_type="agent"
        )
        assert p1.id == p2.id

        rows = (
            (await db_session.execute(select(CommParticipant).where(CommParticipant.thread_id == thread.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_add_participant_rejects_bad_type(db_session):
    tenant = _tk("badtype")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        thread = await repo.create_thread(db_session, tenant, subject="t")
        with pytest.raises(ValidationError):
            await repo.add_participant(db_session, tenant, thread.id, participant_id="x", participant_type="robot")


async def test_threads_are_tenant_isolated(db_session):
    tenant_a = _tk("iso_a")
    tenant_b = _tk("iso_b")
    repo = CommThreadRepository()

    with tenant_session_context(db_session, tenant_a):
        await ensure_default_types_seeded(db_session, tenant_a)
        ta = await repo.create_thread(db_session, tenant_a, subject="a-thread")
    with tenant_session_context(db_session, tenant_b):
        await ensure_default_types_seeded(db_session, tenant_b)
        tb = await repo.create_thread(db_session, tenant_b, subject="b-thread")

    # Each tenant mints its OWN serial sequence starting at 1.
    assert ta.serial == 1
    assert tb.serial == 1

    with tenant_session_context(db_session, tenant_a):
        a_list = await repo.list_threads(db_session, tenant_a)
        assert {t.id for t in a_list} == {ta.id}
        # Cross-tenant read by id returns nothing under tenant A's context.
        assert await repo.get_by_id(db_session, tenant_a, tb.id) is None


async def test_resolution_jsonb_is_validated(db_session):
    tenant = _tk("resolution")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        thread = await repo.create_thread(
            db_session,
            tenant,
            subject="resolved thread",
            status="resolved",
            resolution={"summary": "done", "resolved_by": "user-1", "extra_field": "kept"},
        )
    assert thread.resolution["summary"] == "done"
    assert thread.resolution["resolved_by"] == "user-1"
    # extra="allow" preserves free-form keys.
    assert thread.resolution["extra_field"] == "kept"
