# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0074_messages_thread_created_index"
down_revision = "ce_0073_users_password_nudge_dismissed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON messages (thread_id, created_at)")
    op.execute("DROP INDEX IF EXISTS idx_message_thread")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_message_thread ON messages (thread_id)")
    op.execute("DROP INDEX IF EXISTS idx_messages_thread_created")
