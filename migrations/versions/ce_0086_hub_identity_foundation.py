# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0086_hub_identity_foundation"
down_revision = "ce_0085_heal_giljo_hq_bootstrap_rebrand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    message_columns = [c["name"] for c in inspector.get_columns("messages")]
    if "from_kind" not in message_columns:
        op.add_column(
            "messages",
            sa.Column(
                "from_kind",
                sa.String(length=10),
                nullable=True,
                comment="BE-9289a: author kind ('agent'|'user'), resolved server-side at post time",
            ),
        )

    op.execute(
        sa.text(
            """
            UPDATE messages AS m
               SET from_kind = p.participant_type
              FROM comm_participants AS p
             WHERE p.thread_id = m.thread_id
               AND p.participant_id = m.from_agent_id
               AND p.tenant_key = m.tenant_key
               AND m.from_kind IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE messages AS m
               SET from_kind = 'user'
              FROM users AS u
             WHERE u.id = m.from_agent_id
               AND m.from_kind IS NULL
            """
        )
    )
    op.execute(sa.text("UPDATE messages SET from_kind = 'agent' WHERE from_kind IS NULL"))

    op.execute(sa.text("ALTER TABLE messages ALTER COLUMN from_kind SET DEFAULT 'agent'"))
    op.execute(sa.text("ALTER TABLE messages ALTER COLUMN from_kind SET NOT NULL"))

    participant_columns = [c["name"] for c in inspector.get_columns("comm_participants")]
    if "harness" not in participant_columns:
        op.add_column(
            "comm_participants",
            sa.Column(
                "harness",
                sa.String(length=32),
                nullable=True,
                comment="BE-9289a: harness token stamped from the MCP handshake; never self-declared",
            ),
        )
    if "last_seen_at" not in participant_columns:
        op.add_column(
            "comm_participants",
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="BE-9289a: last post/read/poll on this thread; drives the live-idle indicator",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    participant_columns = [c["name"] for c in inspector.get_columns("comm_participants")]
    if "last_seen_at" in participant_columns:
        op.drop_column("comm_participants", "last_seen_at")
    if "harness" in participant_columns:
        op.drop_column("comm_participants", "harness")

    message_columns = [c["name"] for c in inspector.get_columns("messages")]
    if "from_kind" in message_columns:
        op.drop_column("messages", "from_kind")
