# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0081_download_tokens_staged_at"
down_revision = "ce_0080_widen_comm_agent_id_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("download_tokens")]

    if "staged_at" not in columns:
        op.add_column(
            "download_tokens",
            sa.Column(
                "staged_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="TSK-9210: when this token's ZIP was staged; anchors per-token staleness",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("download_tokens")]

    if "staged_at" in columns:
        op.drop_column("download_tokens", "staged_at")
