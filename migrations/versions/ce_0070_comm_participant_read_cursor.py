# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0070_comm_participant_read_cursor"
down_revision = "ce_0069_dedup_indexes_drift_reconcile"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("last_read_message_id", sa.String(36)),
    ("last_read_at", sa.DateTime(timezone=True)),
)


def _column_exists(conn, column_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.columns"
                "  WHERE table_name = 'comm_participants'"
                "  AND column_name = :col"
                ")"
            ),
            {"col": column_name},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    for name, coltype in _COLUMNS:
        if not _column_exists(conn, name):
            op.add_column("comm_participants", sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    for name, _coltype in reversed(_COLUMNS):
        if _column_exists(conn, name):
            op.drop_column("comm_participants", name)
