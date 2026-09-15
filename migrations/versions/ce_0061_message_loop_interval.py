# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0061_message_loop_interval"
down_revision = "ce_0060_softdelete_recover_template_be6137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.columns"
            "  WHERE table_name = 'messages'"
            "  AND column_name = 'loop_interval_minutes'"
            ")"
        )
    ).scalar()
    if exists:
        return

    op.add_column(
        "messages",
        sa.Column("loop_interval_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "loop_interval_minutes")
