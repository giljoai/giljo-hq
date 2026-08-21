# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8000c: DB index dedup + model<->schema drift reconciliation.

Revision ID: ce_0069_dedup_indexes_drift_reconcile
Revises: ce_0068_purge_completed_sequence_runs
Create Date: 2026-07-01

Structural (usage-independent) waste + drift cleanup from the IMP-6263a DB audit:

1. Drops 45 redundant physical indexes — 17 exact duplicates (a model declared
   BOTH a column-level ``index=True`` AND an explicit ``Index("idx_...")``, so
   the baseline created two identical indexes) + 28 prefix-redundant narrow
   indexes that are fully leftmost-covered by a wider composite (or a UNIQUE
   constraint's backing index). The matching model declarations were removed in
   the same change so autogenerate stays quiet.

2. Adds the missing FK ``oauth_refresh_tokens.user_id -> users.id`` with
   ``ON DELETE CASCADE``. ce_0020 created the column with no FK at all, so on
   installs built via the incremental chain a deleted user orphaned its refresh
   tokens (a real data-integrity gap). The model + baseline already declare the
   CASCADE FK, so fresh installs already have it; this heals older installs.

3. Makes 9 defaulted columns NOT NULL to match the models (they always carry a
   server_default, so NULL was never a valid state): ``users.depth_*`` (6) and
   ``user_field_priorities.{enabled,created_at,updated_at}`` (3). Values are
   backfilled to the server_default first so the ALTER is safe on populated DBs.

DEFERRED (escalated to the orchestrator — a projects-table product decision, not
mechanical dedup): ``projects.product_id`` nullability (DB NOT NULL via ce_0004 vs
model/service nullable) and the ``uq_project_taxonomy_active`` NULLS-NOT-DISTINCT +
stale-comment churn. These interact (relaxing product_id to NULL collides
projectless rows under NULLS NOT DISTINCT) and touch an ADR-009 Teams-readiness
table, so they are intentionally left for a follow-up and remain as known drift.

  RESOLVED — both of the deferrals above are closed; neither is known drift any
  more. ``uq_project_taxonomy_active`` was settled by BE-9429 (the model gained
  ``postgresql_nulls_not_distinct=True``, with a general per-index parity guard
  behind it). ``projects.product_id`` was settled on 2026-08-15 by BE-9437: the
  operator ruled that a project MUST belong to a product, so the decision went
  the DATABASE's way and the model moved to ``nullable=False`` rather than the
  column being relaxed. The drift gate's benign tally lost its
  ``modify_nullable`` entry accordingly, and a column-nullability axis was added
  to the BE-9429 parity guard so the next one fails instead of accumulating.

Idempotent: every DROP is ``DROP INDEX IF EXISTS``; the FK is added only if
absent; each NOT NULL alter runs only while the column is still nullable. The CE
installer reruns ``alembic upgrade head`` on every boot, so a second run is a
clean no-op. Reversible: downgrade recreates the 45 indexes, drops the FK, and
reverts the 9 columns to nullable.

Baseline parity: baseline_v37_unified.py drops the 37 dup index-creation calls it
owned and marks the 9 columns NOT NULL, so a fresh install converges to the same
shape without this migration having to run (the guards make it a no-op there).
The other 8 dropped indexes are created by historical incremental migrations
(comm hub, roadmaps, notifications, login lockouts, taxonomy rename, user
approvals) which stay immutable — this migration's DROP IF EXISTS reconciles them.

NOTE (deferred): ``idx_pme_fts`` (a functional GIN full-text index from ce_0052)
and the 32 comment-only diffs are intentionally NOT touched — Alembic autogenerate
cannot round-trip a functional index expression, and comment drift is cosmetic.
Both are documented as known residual drift, not fixed here.

Edition Scope: Both. Every table is a CE-model table; this migration lives in
migrations/versions/ (never saas_versions/). Nothing here touches the SaaS chain.
"""

from alembic import op
from sqlalchemy import inspect


revision = "ce_0069_dedup_indexes_drift_reconcile"
down_revision = "ce_0068_purge_completed_sequence_runs"
branch_labels = None
depends_on = None


# 45 redundant indexes to drop, paired with the (table, columns[, unique]) needed
# to recreate them on downgrade. All are plain btree indexes (no partial/gin/unique).
_DROPPED_INDEXES: list[tuple[str, str, list[str]]] = [
    # --- 17 exact duplicates (drop the redundant twin) ---
    ("idx_apikey_hash", "api_keys", ["key_hash"]),
    ("ix_api_keys_tenant_key", "api_keys", ["tenant_key"]),
    ("idx_download_token_token", "download_tokens", ["token"]),
    ("ix_mcp_sessions_tenant_key", "mcp_sessions", ["tenant_key"]),
    ("idx_product_architectures_product", "product_architectures", ["product_id"]),
    ("idx_pme_sequence", "product_memory_entries", ["product_id", "sequence"]),
    ("idx_product_tech_stacks_product", "product_tech_stacks", ["product_id"]),
    ("idx_product_test_configs_product", "product_test_configs", ["product_id"]),
    ("ix_products_tenant_key", "products", ["tenant_key"]),
    ("ix_setup_state_database_initialized", "setup_state", ["database_initialized"]),
    ("idx_setup_tenant", "setup_state", ["tenant_key"]),
    ("idx_user_email", "users", ["email"]),
    ("ix_users_tenant_key", "users", ["tenant_key"]),
    ("idx_user_username", "users", ["username"]),
    # settings + download_tokens + vision_documents tenant twins are also
    # prefix-redundant, so BOTH tenant indexes drop (see below).
    ("idx_settings_tenant", "settings", ["tenant_key"]),
    ("idx_download_token_tenant", "download_tokens", ["tenant_key"]),
    ("idx_vision_doc_tenant", "vision_documents", ["tenant_key"]),
    # --- 28 additional prefix-redundant narrow indexes ---
    ("ix_settings_tenant_key", "settings", ["tenant_key"]),
    ("ix_download_tokens_tenant_key", "download_tokens", ["tenant_key"]),
    ("ix_vision_documents_tenant_key", "vision_documents", ["tenant_key"]),
    ("idx_vision_doc_product", "vision_documents", ["product_id"]),
    ("idx_agent_executions_tenant", "agent_executions", ["tenant_key"]),
    ("idx_agent_executions_tenant_job", "agent_executions", ["tenant_key", "job_id"]),
    ("idx_agent_jobs_tenant", "agent_jobs", ["tenant_key"]),
    ("idx_todo_items_job", "agent_todo_items", ["job_id"]),
    ("idx_api_key_ip_log_key_id", "api_key_ip_log", ["api_key_id"]),
    ("idx_comm_participant_tenant", "comm_participants", ["tenant_key"]),
    ("idx_comm_participant_thread", "comm_participants", ["thread_id"]),
    ("idx_comm_thread_tenant", "comm_threads", ["tenant_key"]),
    ("idx_config_tenant", "configurations", ["tenant_key"]),
    ("idx_login_lockout_identifier", "login_lockouts", ["identifier"]),
    ("ix_mcp_context_index_tenant_key", "mcp_context_index", ["tenant_key"]),
    ("idx_mcp_session_expires", "mcp_sessions", ["expires_at"]),
    ("idx_message_acks_message", "message_acknowledgments", ["message_id"]),
    ("idx_message_completions_message", "message_completions", ["message_id"]),
    ("idx_message_recipients_message", "message_recipients", ["message_id"]),
    ("idx_message_tenant", "messages", ["tenant_key"]),
    ("idx_notifications_tenant_key", "notifications", ["tenant_key"]),
    ("idx_membership_org", "org_memberships", ["org_id"]),
    ("idx_assignment_product", "product_agent_assignments", ["product_id"]),
    ("ix_product_memory_entries_tenant_key", "product_memory_entries", ["tenant_key"]),
    ("idx_roadmap_item_roadmap", "roadmap_items", ["roadmap_id"]),
    ("idx_task_tenant", "tasks", ["tenant_key"]),
    ("idx_taxonomy_type_tenant", "taxonomy_types", ["tenant_key"]),
    ("ix_user_approvals_tenant_key", "user_approvals", ["tenant_key"]),
]

# Columns to make NOT NULL, with the server_default value used to backfill any
# pre-existing NULL rows before the ALTER.
_NOT_NULL_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "depth_vision_documents", "'medium'"),
    ("users", "depth_memory_last_n", "3"),
    ("users", "depth_git_commits", "25"),
    ("users", "depth_agent_templates", "'basic'"),
    ("users", "depth_tech_stack_sections", "'all'"),
    ("users", "depth_architecture", "'overview'"),
    ("user_field_priorities", "enabled", "true"),
    ("user_field_priorities", "created_at", "now()"),
    ("user_field_priorities", "updated_at", "now()"),
]

_FK_NAME = "oauth_refresh_tokens_user_id_fkey"


def _column_is_nullable(inspector, table: str, column: str) -> bool:
    for col in inspector.get_columns(table):
        if col["name"] == column:
            return bool(col["nullable"])
    return False


def _fk_on_user_id_exists(inspector) -> bool:
    for fk in inspector.get_foreign_keys("oauth_refresh_tokens"):
        if fk.get("constrained_columns") == ["user_id"] and fk.get("referred_table") == "users":
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Drop the 45 redundant indexes (idempotent).
    for name, _table, _cols in _DROPPED_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")

    # 2. Add the missing oauth_refresh_tokens.user_id -> users.id CASCADE FK
    #    (only on installs that lack it; fresh installs already have it).
    inspector = inspect(bind)
    if not _fk_on_user_id_exists(inspector):
        op.create_foreign_key(
            _FK_NAME,
            "oauth_refresh_tokens",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 3. Make the 9 defaulted columns NOT NULL (backfill NULLs first, guard on
    #    current nullability so fresh installs — already NOT NULL — are a no-op).
    inspector = inspect(bind)
    for table, column, default_sql in _NOT_NULL_COLUMNS:
        if _column_is_nullable(inspector, table, column):
            op.execute(f'UPDATE {table} SET "{column}" = {default_sql} WHERE "{column}" IS NULL')
            op.alter_column(table, column, nullable=False)


def downgrade() -> None:
    bind = op.get_bind()

    # 3. Revert the 9 columns to nullable.
    for table, column, _default in _NOT_NULL_COLUMNS:
        op.alter_column(table, column, nullable=True)

    # 2. Drop the FK this migration added.
    inspector = inspect(bind)
    if _fk_on_user_id_exists(inspector):
        op.drop_constraint(_FK_NAME, "oauth_refresh_tokens", type_="foreignkey")

    # 1. Recreate the 45 dropped indexes (all plain btree; idempotent).
    for name, table, cols in _DROPPED_INDEXES:
        col_list = ", ".join(cols)
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col_list})")
