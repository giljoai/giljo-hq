# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0003_widen_alembic_version"
down_revision = "ce_0002_add_org_deleted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    current_len = conn.execute(
        sa.text(
            "SELECT character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'alembic_version' "
            "AND column_name = 'version_num'"
        )
    ).scalar()
    if current_len is None or current_len >= 64:
        return
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")


def downgrade() -> None:
    pass
