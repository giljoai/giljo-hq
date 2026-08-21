# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469: widen the 360-memory full-text search index to reach git commit messages.

ce_0052 (BE-6082) built ``idx_pme_fts``, an EXPRESSION GIN index, over
summary/project_name/key_outcomes/decisions_made/tags. Black-box QA + operator
ask (2026-08-19) established that a closeout's ``git_commits`` (each entry
``{"sha", "message", "author"?}`` -- see
``jsonb_validators.validate_git_commits``) should be searchable too, e.g.
"when did we fix the redirect bug." The runtime query's document expression
(``_FTS_DOCUMENT_SQL`` in ``src/giljo_mcp/repositories/product_memory_repository.py``)
now includes ``git_commits``; this migration keeps the index in lockstep so the
planner still uses it instead of silently degrading every memory search on this
table to a sequential scan (correct results, quietly no index -- the exact
silent-failure shape ce_0052's byte-identical-expression contract exists to
prevent).

ce_0052 is NOT edited -- it is the historical record of what it actually
shipped, and Alembic migrations are append-only. This migration instead DROPs
and re-CREATEs the SAME index name (``idx_pme_fts``) over the new, wider
expression -- one derived index, redefined in place, no new column, no model
change, no schema-drift gate risk (BE-3002a), identical to ce_0052's own
"expression index, NO new column" design.

Idempotent: ``CREATE INDEX IF NOT EXISTS`` (plain, NOT CONCURRENTLY -- ce_0052's
own precedent, runs inside Alembic's transaction). The DROP INDEX before it is
also idempotent (``IF EXISTS``) and is required here (unlike ce_0052) because a
CREATE INDEX with an unchanged NAME but a CHANGED body is not itself idempotent
-- Postgres does not compare the new expression against what an existing
same-named index actually indexes, so on a second run "IF NOT EXISTS" alone
would see the name already taken and skip, leaving a stale narrower index in
place forever. Dropping first makes every rerun converge on the current,
correct expression regardless of what it inherited.

Reversible: downgrade drops the widened index and recreates ce_0052's original
narrower one, so a rollback restores exactly what was there before this
migration ran -- never a bare drop with no index at all.

Baseline parity (migrations/README.md): ``idx_pme_fts`` also appears verbatim
in ``baseline_v38_unified.py`` (fresh-install path). That raw SQL string is
updated in the SAME commit so a fresh install and an upgraded existing install
converge on the identical index, per the documented ce_0043 parity precedent.

Edition Scope: Both. product_memory_entries is a CE core table; this migration
lives in migrations/versions/ (NOT saas_versions/).
"""

from alembic import op


revision = "ce_0096_pme_fts_git_commits_be9469"
down_revision = "ce_0095_be9431_task_index_nnd"
branch_labels = None
depends_on = None


# ce_0052's ORIGINAL document -- kept here only so downgrade() can restore it
# verbatim. Not imported from ce_0052_pme_fts_be6082.py: migrations must not
# import each other (each is a frozen, standalone step in the chain).
_FTS_DOCUMENT_ORIGINAL = (
    "to_tsvector('english', "
    "coalesce(summary, '') || ' ' || "
    "coalesce(project_name, '') || ' ' || "
    "coalesce(key_outcomes::text, '') || ' ' || "
    "coalesce(decisions_made::text, '') || ' ' || "
    "coalesce(tags::text, ''))"
)

# The WIDENED document. MUST stay byte-identical to ``_FTS_DOCUMENT_SQL`` in
# ``src/giljo_mcp/repositories/product_memory_repository.py`` -- enforced by
# ``tests/repositories/test_be9469_pme_fts_git_commits_parity.py``, not just
# this comment (BE-9469: the first change to either side since ce_0052
# shipped; the test is what stops the second one drifting).
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
