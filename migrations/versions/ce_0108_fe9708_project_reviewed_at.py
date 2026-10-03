# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0108_fe9708_project_reviewed_at"
down_revision = "ce_0107_db9639_drop_tasks_due_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = {c["name"] for c in sa.inspect(conn).get_columns("projects")}
    if "reviewed_at" in columns:
        return
    op.add_column(
        "projects",
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When a human reviewed the finished project (NULL = finished but not yet reviewed)",
        ),
    )
    op.execute(
        "UPDATE projects SET reviewed_at = COALESCE(completed_at, now()) "
        "WHERE status IN ('completed', 'cancelled', 'terminated')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS reviewed_at")
