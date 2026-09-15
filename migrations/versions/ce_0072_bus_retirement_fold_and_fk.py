# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid

import sqlalchemy as sa
from alembic import op


revision = "ce_0072_bus_retirement_fold_and_fk"
down_revision = "ce_0071_agent_todo_item_kind"
branch_labels = None
depends_on = None


_BOUND_THREAD_MARKER = "(project comms)"


def _project_bound_fk(conn) -> tuple[str | None, str | None]:
    row = conn.execute(
        sa.text(
            "SELECT con.conname, con.confdeltype "
            "FROM pg_constraint con "
            "JOIN pg_class rel ON rel.oid = con.conrelid "
            "JOIN pg_attribute att ON att.attrelid = con.conrelid "
            "  AND att.attnum = ANY(con.conkey) "
            "WHERE rel.relname = 'comm_threads' "
            "  AND con.contype = 'f' "
            "  AND att.attname = 'project_id'"
        )
    ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _fold_bus_rows(conn) -> None:
    pairs = conn.execute(
        sa.text(
            "SELECT DISTINCT tenant_key, project_id FROM messages WHERE thread_id IS NULL AND project_id IS NOT NULL"
        )
    ).fetchall()

    for tenant_key, project_id in pairs:
        resolved = conn.execute(
            sa.text(
                "SELECT id FROM comm_threads "
                "WHERE tenant_key = :tk AND project_id = :pid AND deleted_at IS NULL "
                "ORDER BY CASE WHEN subject = :marker THEN 0 ELSE 1 END ASC, created_at ASC "
                "LIMIT 1"
            ),
            {"tk": tenant_key, "pid": project_id, "marker": _BOUND_THREAD_MARKER},
        ).scalar()

        if resolved is None:
            serial = conn.execute(
                sa.text("SELECT COALESCE(MAX(serial), 0) + 1 FROM comm_threads WHERE tenant_key = :tk"),
                {"tk": tenant_key},
            ).scalar()
            product_id = conn.execute(
                sa.text("SELECT product_id FROM projects WHERE id = :pid"),
                {"pid": project_id},
            ).scalar()
            resolved = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO comm_threads "
                    "(id, tenant_key, serial, subject, status, product_id, project_id, created_at, updated_at) "
                    "VALUES (:id, :tk, :serial, :subject, 'open', :product_id, :pid, now(), now())"
                ),
                {
                    "id": resolved,
                    "tk": tenant_key,
                    "serial": serial,
                    "subject": _BOUND_THREAD_MARKER,
                    "product_id": product_id,
                    "pid": project_id,
                },
            )

        conn.execute(
            sa.text(
                "UPDATE messages SET thread_id = :tid "
                "WHERE tenant_key = :tk AND project_id = :pid AND thread_id IS NULL"
            ),
            {"tid": resolved, "tk": tenant_key, "pid": project_id},
        )


def upgrade() -> None:
    conn = op.get_bind()

    _fold_bus_rows(conn)

    conname, deltype = _project_bound_fk(conn)
    if conname is not None and deltype != "c":
        op.execute(f'ALTER TABLE comm_threads DROP CONSTRAINT "{conname}"')
        op.execute(
            'ALTER TABLE comm_threads ADD CONSTRAINT "comm_threads_project_id_fkey" '
            "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
        )


def downgrade() -> None:
    conn = op.get_bind()
    conname, deltype = _project_bound_fk(conn)
    if conname is not None and deltype != "n":
        op.execute(f'ALTER TABLE comm_threads DROP CONSTRAINT "{conname}"')
        op.execute(
            'ALTER TABLE comm_threads ADD CONSTRAINT "comm_threads_project_id_fkey" '
            "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL"
        )
