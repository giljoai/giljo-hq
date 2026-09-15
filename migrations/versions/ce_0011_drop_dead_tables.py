# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "ce_0011_drop_dead_tables"
down_revision = "ce_0010_drop_projects_paused_at"
branch_labels = None
depends_on = None


def _has_table(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, "git_commits"):
        op.drop_table("git_commits")
    if _has_table(conn, "template_usage_stats"):
        op.drop_table("template_usage_stats")


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "git_commits"):
        op.create_table(
            "git_commits",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("commit_hash", sa.String(length=40), nullable=False, unique=True),
            sa.Column("commit_message", sa.Text(), nullable=False),
            sa.Column("author_name", sa.String(length=100), nullable=False),
            sa.Column("author_email", sa.String(length=255), nullable=False),
            sa.Column("branch_name", sa.String(length=100), nullable=False),
            sa.Column("files_changed", JSONB(), nullable=True),
            sa.Column("insertions", sa.Integer(), nullable=True),
            sa.Column("deletions", sa.Integer(), nullable=True),
            sa.Column("triggered_by", sa.String(length=50), nullable=True),
            sa.Column("commit_type", sa.String(length=50), nullable=True),
            sa.Column("push_status", sa.String(length=20), nullable=True),
            sa.Column("push_error", sa.Text(), nullable=True),
            sa.Column("webhook_triggered", sa.Boolean(), nullable=True),
            sa.Column("webhook_response", JSONB(), nullable=True),
            sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.CheckConstraint(
                "push_status IN ('pending', 'pushed', 'failed')",
                name="ck_git_commit_push_status",
            ),
        )
        op.create_index("idx_git_commit_tenant", "git_commits", ["tenant_key"])
        op.create_index("idx_git_commit_product", "git_commits", ["product_id"])
        op.create_index("idx_git_commit_project", "git_commits", ["project_id"])
        op.create_index("idx_git_commit_hash", "git_commits", ["commit_hash"])
        op.create_index("idx_git_commit_date", "git_commits", ["committed_at"])
        op.create_index("idx_git_commit_trigger", "git_commits", ["triggered_by"])

    if not _has_table(conn, "template_usage_stats"):
        op.create_table(
            "template_usage_stats",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("template_id", sa.String(length=36), sa.ForeignKey("agent_templates.id"), nullable=False),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("used_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("generation_ms", sa.Integer(), nullable=True),
            sa.Column("variables_used", JSONB(), nullable=True),
            sa.Column("augmentations_applied", JSONB(), nullable=True),
            sa.Column("agent_completed", sa.Boolean(), nullable=True),
            sa.Column("agent_success_rate", sa.Float(), nullable=True),
            sa.Column("tokens_used", sa.Integer(), nullable=True),
        )
        op.create_index("idx_usage_tenant", "template_usage_stats", ["tenant_key"])
        op.create_index("idx_usage_template", "template_usage_stats", ["template_id"])
        op.create_index("idx_usage_project", "template_usage_stats", ["project_id"])
        op.create_index("idx_usage_date", "template_usage_stats", ["used_at"])
