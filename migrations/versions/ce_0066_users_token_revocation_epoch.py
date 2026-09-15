# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0066_users_token_revocation_epoch"
down_revision = "ce_0065_sequence_run_chain_mission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.columns"
            "  WHERE table_name = 'users'"
            "  AND column_name = 'token_revocation_epoch'"
            ")"
        )
    ).scalar()
    if exists:
        return

    op.add_column(
        "users",
        sa.Column(
            "token_revocation_epoch",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_revocation_epoch")
