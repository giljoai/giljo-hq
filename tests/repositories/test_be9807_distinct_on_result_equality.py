# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
import warnings
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, Project
from giljo_mcp.models.comm import (
    LOOP_DIRECTIVE_MESSAGE_TYPE,
    TERMINAL_THREAD_STATUSES,
    CommParticipant,
    CommThread,
)
from giljo_mcp.models.product_memory_entry import ProductMemoryEntry
from giljo_mcp.models.tasks import Message
from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded


pytestmark = pytest.mark.asyncio

AGENT = "agent-be9807"


def _tk(suffix: str) -> str:
    return f"tk_be9807_{suffix}_{uuid.uuid4().hex[:6]}"


def _legacy(stmt_builder):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return stmt_builder()


async def _capture_sql(db_session, coro_factory) -> tuple[object, list[str]]:
    statements: list[str] = []
    sync_conn = (await db_session.connection()).sync_connection

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(sync_conn, "before_cursor_execute", _record)
    try:
        result = await coro_factory()
    finally:
        event.remove(sync_conn, "before_cursor_execute", _record)
    return result, statements


def _legacy_loop_directive_stmt(tenant_key: str, agent_id: str):
    latest = (
        select(
            Message.thread_id.label("thread_id"),
            Message.loop_interval_minutes.label("interval_minutes"),
        )
        .where(
            Message.tenant_key == tenant_key,
            Message.message_type == LOOP_DIRECTIVE_MESSAGE_TYPE,
            Message.thread_id.isnot(None),
        )
        .order_by(Message.thread_id, Message.created_at.desc(), Message.id.desc())
        .distinct(Message.thread_id)
        .subquery()
    )
    return (
        select(CommThread.id, CommThread.serial, latest.c.interval_minutes)
        .join(latest, latest.c.thread_id == CommThread.id)
        .join(CommParticipant, CommParticipant.thread_id == CommThread.id)
        .where(
            CommThread.tenant_key == tenant_key,
            CommThread.deleted_at.is_(None),
            CommThread.status.notin_(TERMINAL_THREAD_STATUSES),
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.participant_id == agent_id,
        )
    )


def _legacy_closeout_stmt(tenant_key: str, project_ids: list[str]):
    return (
        select(ProductMemoryEntry.project_id, ProductMemoryEntry.summary)
        .where(
            ProductMemoryEntry.project_id.in_(project_ids),
            ProductMemoryEntry.tenant_key == tenant_key,
            ProductMemoryEntry.entry_type.in_(("project_closeout", "project_completion")),
            ProductMemoryEntry.deleted_by_user.is_(False),
            ProductMemoryEntry.summary.is_not(None),
        )
        .distinct(ProductMemoryEntry.project_id)
        .order_by(ProductMemoryEntry.project_id, ProductMemoryEntry.sequence.desc())
    )


async def _post_directive(repo, db_session, tenant: str, thread_id: str, minutes: int) -> None:
    await repo.persist_thread_message(
        db_session,
        tenant_key=tenant,
        thread_id=thread_id,
        project_id=None,
        content=f"loop every {minutes}",
        from_agent_id="orchestrator",
        from_display_name="orchestrator",
        message_type=LOOP_DIRECTIVE_MESSAGE_TYPE,
        priority="normal",
        requires_action=False,
        recipient_ids=[],
        loop_interval_minutes=minutes,
    )


async def test_loop_directive_read_matches_the_legacy_distinct(db_session):
    tenant = _tk("loop")
    repo = CommThreadRepository()
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)
        joined = [await repo.create_thread(db_session, tenant, subject=f"joined {i}") for i in range(3)]
        not_joined = await repo.create_thread(db_session, tenant, subject="not joined")
        for thread in joined:
            await repo.add_participant(db_session, tenant, thread.id, participant_id=AGENT, participant_type="agent")
        for offset, thread in enumerate([*joined, not_joined]):
            for minutes in (5 + offset, 10 + offset, 15 + offset):
                await _post_directive(repo, db_session, tenant, thread.id, minutes)
        await db_session.flush()

        new_rows, new_sql = await _capture_sql(
            db_session, lambda: repo.get_active_loop_directives_for_agent(db_session, tenant, AGENT)
        )
        legacy_stmt = _legacy(lambda: _legacy_loop_directive_stmt(tenant, AGENT))
        legacy_result, legacy_sql = await _capture_sql(db_session, lambda: db_session.execute(legacy_stmt))
        legacy_rows = [
            {"thread_id": r.id, "serial": r.serial, "interval_minutes": r.interval_minutes} for r in legacy_result.all()
        ]

    assert len(new_rows) == len(joined), new_rows
    assert {row["thread_id"] for row in new_rows} == {t.id for t in joined}
    assert new_rows == legacy_rows
    assert "DISTINCT ON (messages.thread_id)" in new_sql[-1], new_sql
    assert new_sql[-1] == legacy_sql[-1], "the repository's SQL differs from the legacy .distinct() statement"


async def test_latest_closeout_summary_read_matches_the_legacy_distinct(db_session):
    tenant = _tk("closeout")
    now = datetime.now(UTC)
    with tenant_session_context(db_session, tenant):
        product = Product(id=str(uuid.uuid4()), name=f"BE-9807 {uuid.uuid4().hex[:6]}", tenant_key=tenant)
        db_session.add(product)
        await db_session.flush()
        projects = [
            Project(
                id=str(uuid.uuid4()),
                name=f"BE-9807 p{i}",
                description="distinct_on proof",
                mission="",
                status="completed",
                tenant_key=tenant,
                product_id=product.id,
                series_number=i + 1,
                created_at=now,
                completed_at=now,
            )
            for i in range(3)
        ]
        db_session.add_all(projects)
        await db_session.flush()
        sequence = 0
        for project in projects:
            for entry_type in ("project_closeout", "project_completion", "project_closeout"):
                sequence += 1
                db_session.add(
                    ProductMemoryEntry(
                        tenant_key=tenant,
                        product_id=product.id,
                        project_id=project.id,
                        sequence=sequence,
                        entry_type=entry_type,
                        source="closeout_v1",
                        timestamp=now,
                        summary=f"{project.name} closeout #{sequence}",
                    )
                )
        await db_session.flush()
        project_ids = [p.id for p in projects]

        new_result, new_sql = await _capture_sql(
            db_session, lambda: ProjectRepository().get_latest_closeout_summaries(db_session, tenant, project_ids)
        )
        legacy_stmt = _legacy(lambda: _legacy_closeout_stmt(tenant, project_ids))
        legacy_result, legacy_sql = await _capture_sql(db_session, lambda: db_session.execute(legacy_stmt))
        legacy_pairs = [(row[0], row[1]) for row in legacy_result.all()]

    assert list(new_result.items()) == legacy_pairs
    assert sorted(new_result.values()) == sorted(f"BE-9807 p{i} closeout #{3 * (i + 1)}" for i in range(3))
    assert "DISTINCT ON (product_memory_entries.project_id)" in new_sql[-1], new_sql
    assert new_sql[-1] == legacy_sql[-1], "the repository's SQL differs from the legacy .distinct() statement"
