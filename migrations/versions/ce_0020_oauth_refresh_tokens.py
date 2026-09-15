# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ce_0020_oauth_refresh_tokens"
down_revision = "ce_0019_oauth_codes_resource"
branch_labels = None
depends_on = None


TABLE = "oauth_refresh_tokens"


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :name)"),
            {"name": name},
        ).scalar()
    )


def _index_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = :name)"),
            {"name": name},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("family_id", postgresql.UUID(as_uuid=False), nullable=False),
            sa.Column("client_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_key", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("aud", sa.Text(), nullable=False),
            sa.Column(
                "issued_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "revoked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _index_exists(conn, "ix_oauth_refresh_tokens_family_id"):
        op.create_index("ix_oauth_refresh_tokens_family_id", TABLE, ["family_id"])

    if not _index_exists(conn, "ix_oauth_refresh_tokens_tenant_key"):
        op.create_index("ix_oauth_refresh_tokens_tenant_key", TABLE, ["tenant_key"])


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(conn, "ix_oauth_refresh_tokens_tenant_key"):
        op.drop_index("ix_oauth_refresh_tokens_tenant_key", table_name=TABLE)

    if _index_exists(conn, "ix_oauth_refresh_tokens_family_id"):
        op.drop_index("ix_oauth_refresh_tokens_family_id", table_name=TABLE)

    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
