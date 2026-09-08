# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9530 -- a thread may tag several projects, not only the one it is bound to.

Revision ID: ce_0101_fe9530_comm_thread_project_tags
Revises: ce_0100_be9525b_drop_single_active_project
Create Date: 2026-08-30

Operator ruling 3 (FE-9530, 2026-08-29): "a thread must tag a product and MAY tag
projects -- one, several, or none. Do not build a single-project foreign key and
call it done." ``comm_threads.project_id`` IS exactly that single foreign key --
it answers "whose bound thread is this" (the BE-9012d lifecycle binding, CASCADE
with the project), not "which projects does this conversation touch."

This migration adds the second answer as a new, purely additive many-to-many
table. ``project_id`` is UNCHANGED -- no column dropped, no data moved, no
existing row rewritten. That is deliberate: this is schema capability, not a
data-facing convention change, so there is nothing to backfill and nothing for
old rows to tolerate. A thread created before this table existed simply has zero
tag rows, which reads identically to "no additional projects tagged."

Operations
----------
1. Create ``comm_thread_project_tags`` (id, tenant_key, thread_id, project_id,
   created_at). CASCADE on both FKs -- a tag is metadata about a conversation,
   not a lifecycle link (unlike ``comm_threads.project_id``), so it should not
   outlive either side.
2. Unique (thread_id, project_id) -- a thread tags a given project at most once.
3. Index the reverse lookup (tenant_key, project_id) for "which threads mention
   project X," and a plain index on thread_id for the forward read.

Idempotency
-----------
``inspect().has_table()`` guards table creation; the whole migration is a no-op
on a second run, matching every other CE migration's contract with the installer
that reruns the chain on every boot.

Edition Scope: CE -- ``comm_threads`` and ``projects`` are both CE tables.
"""

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
