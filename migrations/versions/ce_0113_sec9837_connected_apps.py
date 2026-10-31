# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0113_sec9837_connected_apps"
down_revision = "ce_0112_heal_worker_bootstrap_first_call"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "oauth_logins" not in tables:
        op.create_table(
            "oauth_logins",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("family_id", sa.UUID(), nullable=False),
            sa.Column("tenant_key", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("client_id", sa.String(length=256), nullable=False),
            sa.Column("client_name", sa.String(length=200), nullable=False),
            sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_ip", sa.String(length=45), nullable=True),
            sa.Column("last_user_agent", sa.String(length=256), nullable=True),
            sa.Column("last_mcp_client_name", sa.String(length=128), nullable=True),
            sa.Column("last_mcp_client_version", sa.String(length=64), nullable=True),
            sa.Column("last_product_id", sa.String(length=36), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["last_product_id"], ["products.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="oauth_logins_pkey"),
            sa.UniqueConstraint("family_id", name="oauth_logins_family_id_key"),
        )
        op.create_index("ix_oauth_logins_tenant_user", "oauth_logins", ["tenant_key", "user_id"])

    if "oauth_login_ips" not in tables:
        op.create_table(
            "oauth_login_ips",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("login_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=64), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=False),
            sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.ForeignKeyConstraint(["login_id"], ["oauth_logins.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="oauth_login_ips_pkey"),
            sa.UniqueConstraint("login_id", "ip_address", name="uq_oauth_login_ip"),
        )
        op.create_index("ix_oauth_login_ips_tenant_key", "oauth_login_ips", ["tenant_key"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "oauth_login_ips" in tables:
        op.drop_table("oauth_login_ips")
    if "oauth_logins" in tables:
        op.drop_table("oauth_logins")
