# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0055_users_registration_ip"
down_revision = "ce_0054_cht_taxonomy_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.columns"
            "  WHERE table_name = 'users'"
            "  AND column_name = 'registration_ip'"
            ")"
        )
    ).scalar()
    if exists:
        return

    op.add_column(
        "users",
        sa.Column("registration_ip", sa.String(length=45), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "registration_ip")
