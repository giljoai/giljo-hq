# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0021_oauth_codes_scope_default"
down_revision = "ce_0020_oauth_refresh_tokens"
branch_labels = None
depends_on = None


TABLE = "oauth_authorization_codes"
COLUMN = "scope"
NEW_DEFAULT = "mcp:read mcp:write"
OLD_DEFAULT = "mcp"


def upgrade() -> None:
    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.String(length=512),
        server_default=sa.text(f"'{NEW_DEFAULT}'"),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.String(length=512),
        server_default=sa.text(f"'{OLD_DEFAULT}'"),
        existing_nullable=True,
    )
