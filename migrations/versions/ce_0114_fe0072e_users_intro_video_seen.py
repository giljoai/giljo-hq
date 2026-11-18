# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0114_fe0072e_users_intro_video_seen"
down_revision = "ce_0113_sec9837_connected_apps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "intro_video_seen" in columns:
        return
    op.add_column(
        "users",
        sa.Column("intro_video_seen", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.alter_column("users", "intro_video_seen", server_default=sa.text("false"))


def downgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "intro_video_seen" in columns:
        op.drop_column("users", "intro_video_seen")
