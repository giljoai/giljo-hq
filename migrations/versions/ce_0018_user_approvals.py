# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0018_user_approvals"
down_revision = "ce_0017_tasks_add_series_number_subseries"
branch_labels = None
depends_on = None


TABLE = "user_approvals"


def _has_table(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def _has_index(conn, index: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index"),
        {"index": index},
    )
    return result.first() is not None


def _has_check_constraint(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :name AND constraint_type = 'CHECK'"
        ),
        {"name": name},
    )
    return result.first() is not None


_AGENT_STATUS_CHECK_OLD = (
    "status IN ('waiting', 'working', 'blocked', 'complete', 'closed', 'silent', 'decommissioned', 'idle', 'sleeping')"
)
_AGENT_STATUS_CHECK_NEW = (
    "status IN ('waiting', 'working', 'blocked', 'complete', 'closed', "
    "'silent', 'decommissioned', 'idle', 'sleeping', 'awaiting_user')"
)


def upgrade() -> None:
    conn = op.get_bind()

    if _has_check_constraint(conn, "ck_agent_execution_status"):
        op.drop_constraint("ck_agent_execution_status", "agent_executions", type_="check")
    op.create_check_constraint(
        "ck_agent_execution_status",
        "agent_executions",
        _AGENT_STATUS_CHECK_NEW,
    )

    if not _has_table(conn, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=50), nullable=False),
            sa.Column(
                "agent_execution_id",
                sa.String(length=36),
                sa.ForeignKey("agent_executions.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "job_id",
                sa.String(length=36),
                sa.ForeignKey("agent_jobs.job_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("projects.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column(
                "options",
                sa.dialects.postgresql.JSONB(),
                nullable=False,
            ),
            sa.Column(
                "context",
                sa.dialects.postgresql.JSONB(),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("decided_option_id", sa.String(length=100), nullable=True),
            sa.Column(
                "decided_by_user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "requested_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending', 'decided', 'expired', 'cancelled')",
                name="ck_user_approvals_status",
            ),
        )

    if not _has_index(conn, "ix_user_approvals_tenant_status"):
        op.create_index(
            "ix_user_approvals_tenant_status",
            TABLE,
            ["tenant_key", "status"],
        )

    if not _has_index(conn, "ix_user_approvals_agent_status"):
        op.create_index(
            "ix_user_approvals_agent_status",
            TABLE,
            ["agent_execution_id", "status"],
        )

    if not _has_index(conn, "ix_user_approvals_tenant_key"):
        op.create_index(
            "ix_user_approvals_tenant_key",
            TABLE,
            ["tenant_key"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_index(conn, "ix_user_approvals_tenant_key"):
        op.drop_index("ix_user_approvals_tenant_key", table_name=TABLE)
    if _has_index(conn, "ix_user_approvals_agent_status"):
        op.drop_index("ix_user_approvals_agent_status", table_name=TABLE)
    if _has_index(conn, "ix_user_approvals_tenant_status"):
        op.drop_index("ix_user_approvals_tenant_status", table_name=TABLE)

    if _has_table(conn, TABLE):
        op.drop_table(TABLE)

    if _has_check_constraint(conn, "ck_agent_execution_status"):
        op.drop_constraint("ck_agent_execution_status", "agent_executions", type_="check")
    op.create_check_constraint(
        "ck_agent_execution_status",
        "agent_executions",
        _AGENT_STATUS_CHECK_OLD,
    )
