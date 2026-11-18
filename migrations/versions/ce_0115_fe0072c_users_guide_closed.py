# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0115_fe0072c_users_guide_closed"
down_revision = "ce_0114_fe0072e_users_intro_video_seen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "guide_closed" in columns:
        return
    op.add_column("users", sa.Column("guide_closed", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "guide_closed" in columns:
        op.drop_column("users", "guide_closed")
