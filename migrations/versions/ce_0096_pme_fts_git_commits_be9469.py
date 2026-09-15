# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0096_pme_fts_git_commits_be9469"
down_revision = "ce_0095_be9431_task_index_nnd"
branch_labels = None
depends_on = None


_FTS_DOCUMENT_ORIGINAL = (
    "to_tsvector('english', "
    "coalesce(summary, '') || ' ' || "
    "coalesce(project_name, '') || ' ' || "
    "coalesce(key_outcomes::text, '') || ' ' || "
    "coalesce(decisions_made::text, '') || ' ' || "
    "coalesce(tags::text, ''))"
)

_FTS_DOCUMENT = (
    "to_tsvector('english', "
    "coalesce(summary, '') || ' ' || "
    "coalesce(project_name, '') || ' ' || "
    "coalesce(key_outcomes::text, '') || ' ' || "
    "coalesce(decisions_made::text, '') || ' ' || "
    "coalesce(tags::text, '') || ' ' || "
    "coalesce(git_commits::text, ''))"
)


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pme_fts")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_pme_fts ON product_memory_entries USING gin ({_FTS_DOCUMENT})")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pme_fts")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_pme_fts ON product_memory_entries USING gin ({_FTS_DOCUMENT_ORIGINAL})")
