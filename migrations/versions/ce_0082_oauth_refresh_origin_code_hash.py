# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0082_oauth_refresh_origin_code_hash"
down_revision = "ce_0081_download_tokens_staged_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("oauth_refresh_tokens")]

    if "origin_code_hash" not in columns:
        op.add_column(
            "oauth_refresh_tokens",
            sa.Column(
                "origin_code_hash",
                sa.String(length=64),
                nullable=True,
                comment="SEC-9227b: sha256 hex of the auth code that minted this family; enables reuse-revocation",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("oauth_refresh_tokens")]

    if "origin_code_hash" in columns:
        op.drop_column("oauth_refresh_tokens", "origin_code_hash")
