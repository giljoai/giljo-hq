# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0109_be9755_template_proposals"
down_revision = "ce_0108_fe9708_project_reviewed_at"
branch_labels = None
depends_on = None


TABLE = "template_proposals"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table(TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("slot_key", sa.String(length=80), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=True),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("rung", sa.String(length=16), nullable=True),
        sa.Column("proposed_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("proposed_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("replaced_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["agent_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key", "slot_key", name="uq_template_proposal_tenant_slot"),
    )
    op.create_index("idx_template_proposal_tenant", TABLE, ["tenant_key"])


def downgrade() -> None:
    if not _has_table(TABLE):
        return
    op.drop_index("idx_template_proposal_tenant", table_name=TABLE)
    op.drop_table(TABLE)
