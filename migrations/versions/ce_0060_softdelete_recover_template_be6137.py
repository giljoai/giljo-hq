# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0060_softdelete_recover_template_be6137"
down_revision = "ce_0059_softdelete_recover_be6130b"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = :t AND column_name = :c)"
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def _index_exists(conn, index: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = :i)"),
            {"i": index},
        ).scalar()
    )


def _index_def_contains(conn, index: str, needle: str) -> bool:
    indexdef = conn.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :i"),
        {"i": index},
    ).scalar()
    return bool(indexdef) and needle in indexdef


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "agent_templates", "deleted_at"):
        op.add_column(
            "agent_templates",
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Timestamp when template was soft deleted (NULL for live templates)",
            ),
        )

    if not _index_exists(conn, "idx_template_deleted_at"):
        op.create_index(
            "idx_template_deleted_at",
            "agent_templates",
            ["deleted_at"],
            postgresql_where=sa.text("deleted_at IS NOT NULL"),
        )

    if not _index_def_contains(conn, "uq_template_tenant_name_version", "deleted_at"):
        op.execute("ALTER TABLE agent_templates DROP CONSTRAINT IF EXISTS uq_template_tenant_name_version")
        op.execute("DROP INDEX IF EXISTS uq_template_tenant_name_version")
        op.create_index(
            "uq_template_tenant_name_version",
            "agent_templates",
            ["tenant_key", "name", "version"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _index_def_contains(conn, "uq_template_tenant_name_version", "deleted_at"):
        op.execute("DROP INDEX IF EXISTS uq_template_tenant_name_version")
        op.create_unique_constraint(
            "uq_template_tenant_name_version",
            "agent_templates",
            ["tenant_key", "name", "version"],
        )

    if _index_exists(conn, "idx_template_deleted_at"):
        op.drop_index("idx_template_deleted_at", table_name="agent_templates")

    if _column_exists(conn, "agent_templates", "deleted_at"):
        op.drop_column("agent_templates", "deleted_at")
