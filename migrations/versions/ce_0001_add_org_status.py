# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0001_add_org_status"
down_revision = "baseline_v37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.columns"
            "  WHERE table_name = 'organizations'"
            "  AND column_name = 'status'"
            ")"
        )
    ).scalar()
    if exists:
        return

    op.add_column(
        "organizations",
        sa.Column("status", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "status")
