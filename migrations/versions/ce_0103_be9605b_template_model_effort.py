# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0103_be9605b_template_model_effort"
down_revision = "ce_0102_be9540_sequence_run_reviewed_via"
branch_labels = None
depends_on = None

_TABLE = "agent_templates"


def _column_length(conn, column_name: str) -> int | None:
    return conn.execute(
        sa.text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": _TABLE, "col": column_name},
    ).scalar()


def _column_exists(conn, column_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = :table AND column_name = :col)"
            ),
            {"table": _TABLE, "col": column_name},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()

    if _column_exists(conn, "model") and (_column_length(conn, "model") or 0) < 120:
        op.alter_column(_TABLE, "model", type_=sa.String(length=120), existing_type=sa.String(length=20))
    if _column_exists(conn, "model"):
        op.execute(sa.text("UPDATE agent_templates SET model = 'inherit' WHERE model IS NULL OR btrim(model) = ''"))

    if not _column_exists(conn, "effort"):
        op.add_column(
            _TABLE,
            sa.Column("effort", sa.String(length=120), nullable=False, server_default="inherit"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "effort"):
        op.drop_column(_TABLE, "effort")
    op.execute(sa.text("UPDATE agent_templates SET model = left(model, 20) WHERE model IS NOT NULL"))
    op.alter_column(_TABLE, "model", type_=sa.String(length=20), existing_type=sa.String(length=120))
