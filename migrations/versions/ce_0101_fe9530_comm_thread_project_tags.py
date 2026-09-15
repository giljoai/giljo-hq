# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0101_fe9530_comm_thread_project_tags"
down_revision = "ce_0100_be9525b_drop_single_active_project"
branch_labels = None
depends_on = None

_TABLE = "comm_thread_project_tags"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column(
                "thread_id",
                sa.String(length=36),
                sa.ForeignKey("comm_threads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("thread_id", "project_id", name="uq_comm_thread_project_tag"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)} if inspector.has_table(_TABLE) else set()
    if "idx_comm_thread_project_tag_thread" not in existing_indexes:
        op.create_index("idx_comm_thread_project_tag_thread", _TABLE, ["thread_id"])
    if "idx_comm_thread_project_tag_project" not in existing_indexes:
        op.create_index("idx_comm_thread_project_tag_project", _TABLE, ["tenant_key", "project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(_TABLE):
        op.drop_table(_TABLE)
