# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import inspect


revision = "ce_0075_projects_ever_launched_at"
down_revision = "ce_0074_messages_thread_created_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("projects")]
    if "ever_launched_at" not in columns:
        op.execute("ALTER TABLE projects ADD COLUMN ever_launched_at TIMESTAMPTZ NULL")
    op.execute(
        "UPDATE projects SET ever_launched_at = implementation_launched_at "
        "WHERE implementation_launched_at IS NOT NULL AND ever_launched_at IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS ever_launched_at")
