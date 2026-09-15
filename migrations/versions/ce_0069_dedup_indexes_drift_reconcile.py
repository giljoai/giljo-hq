# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import inspect


revision = "ce_0069_dedup_indexes_drift_reconcile"
down_revision = "ce_0068_purge_completed_sequence_runs"
branch_labels = None
depends_on = None


_DROPPED_INDEXES: list[tuple[str, str, list[str]]] = [
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
    ("idx_settings_tenant", "settings", ["tenant_key"]),
    ("idx_download_token_tenant", "download_tokens", ["tenant_key"]),
    ("idx_vision_doc_tenant", "vision_documents", ["tenant_key"]),
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

    for name, _table, _cols in _DROPPED_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")

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

    inspector = inspect(bind)
    for table, column, default_sql in _NOT_NULL_COLUMNS:
        if _column_is_nullable(inspector, table, column):
            op.execute(f'UPDATE {table} SET "{column}" = {default_sql} WHERE "{column}" IS NULL')
            op.alter_column(table, column, nullable=False)


def downgrade() -> None:
    bind = op.get_bind()

    for table, column, _default in _NOT_NULL_COLUMNS:
        op.alter_column(table, column, nullable=True)

    inspector = inspect(bind)
    if _fk_on_user_id_exists(inspector):
        op.drop_constraint(_FK_NAME, "oauth_refresh_tokens", type_="foreignkey")

    for name, table, cols in _DROPPED_INDEXES:
        col_list = ", ".join(cols)
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col_list})")
