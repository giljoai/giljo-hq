# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "baseline_v37"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("org_setup_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_org_tenant", "organizations", ["tenant_key"], unique=False)
    op.create_index("idx_org_slug", "organizations", ["slug"], unique=True)
    op.create_index("idx_org_active", "organizations", ["is_active"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            nullable=True,
            comment="Direct foreign key to organization (Handover 0424m - nullable for SET NULL)",
        ),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "recovery_pin_hash",
            sa.String(length=255),
            nullable=True,
            comment="Bcrypt hash of 4-digit recovery PIN for password reset",
        ),
        sa.Column(
            "failed_pin_attempts",
            sa.Integer(),
            nullable=False,
            comment="Number of failed PIN verification attempts (rate limiting)",
        ),
        sa.Column(
            "pin_lockout_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when PIN lockout expires (15 minutes after 5 failed attempts)",
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            comment="Force user to change password on next login (new users, admin reset)",
        ),
        sa.Column(
            "must_set_pin",
            sa.Boolean(),
            nullable=False,
            comment="Force user to set recovery PIN on next login (new users)",
        ),
        sa.Column("is_system_user", sa.Boolean(), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "notification_preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="User notification preferences: tuning reminders, thresholds",
        ),
        sa.Column("depth_vision_documents", sa.String(length=20), server_default=sa.text("'medium'"), nullable=False),
        sa.Column("depth_memory_last_n", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("depth_git_commits", sa.Integer(), server_default=sa.text("25"), nullable=False),
        sa.Column("depth_agent_templates", sa.String(length=20), server_default=sa.text("'basic'"), nullable=False),
        sa.Column("depth_tech_stack_sections", sa.String(length=20), server_default=sa.text("'all'"), nullable=False),
        sa.Column("depth_architecture", sa.String(length=20), server_default=sa.text("'overview'"), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), server_default=sa.text("'claude_code'"), nullable=True),
        sa.Column("setup_complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("setup_selected_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("setup_step_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("learning_complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "password_nudge_dismissed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="BE-1004: one-time 'set a password' nudge dismissal for social-only users",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.CheckConstraint("role IN ('admin', 'developer', 'viewer')", name="ck_user_role"),
        sa.CheckConstraint("failed_pin_attempts >= 0", name="ck_user_pin_attempts_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_tenant", "users", ["tenant_key"], unique=False)
    op.create_index("idx_user_active", "users", ["is_active"], unique=False)
    op.create_index("idx_user_system", "users", ["is_system_user"], unique=False)
    op.create_index("idx_user_pin_lockout", "users", ["pin_lockout_until"], unique=False)
    op.create_index("idx_user_org_id", "users", ["org_id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "org_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("invited_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_user"),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name="ck_membership_role"),
    )
    op.create_index("idx_membership_user", "org_memberships", ["user_id"], unique=False)
    op.create_index("idx_membership_tenant", "org_memberships", ["tenant_key"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(is_active = true AND revoked_at IS NULL) OR (is_active = false)", name="ck_apikey_revoked_consistency"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_apikey_tenant", "api_keys", ["tenant_key"], unique=False)
    op.create_index("idx_apikey_user", "api_keys", ["user_id"], unique=False)
    op.create_index("idx_apikey_active", "api_keys", ["is_active"], unique=False)
    op.create_index("idx_apikey_permissions_gin", "api_keys", ["permissions"], unique=False, postgresql_using="gin")
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "api_key_ip_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_id", "ip_address", name="uq_api_key_ip"),
    )
    op.create_index("idx_api_key_ip_log_last_seen", "api_key_ip_log", ["last_seen_at"], unique=False)

    op.create_table(
        "products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column(
            "org_id", sa.String(length=36), nullable=True, comment="Organization that owns this product (Handover 0424)"
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "project_path",
            sa.String(length=500),
            nullable=True,
            comment="File system path to product folder (required for agent export)",
        ),
        sa.Column("quality_standards", sa.Text(), nullable=True, comment="Quality standards and testing expectations"),
        sa.Column(
            "target_platforms",
            sa.ARRAY(sa.String()),
            server_default=sa.text("'{all}'::text[]"),
            nullable=False,
            comment="Target platforms: windows, linux, macos, android, ios, web, or all",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when product was soft deleted (NULL for active products)",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            comment="Active product for token estimation and mission planning (one per tenant)",
        ),
        sa.Column(
            "product_memory",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text('\'{"github": {}, "context": {}}\'::jsonb'),
            nullable=False,
            comment="Product memory config storage. Contains git_integration settings only.",
        ),
        sa.Column(
            "tuning_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Context tuning state: last_tuned_at, last_tuned_at_sequence",
        ),
        sa.Column(
            "consolidated_vision_light",
            sa.Text(),
            nullable=True,
            comment="33% summary of all active vision documents (consolidated)",
        ),
        sa.Column(
            "consolidated_vision_light_tokens",
            sa.Integer(),
            nullable=True,
            comment="Token count of consolidated light summary",
        ),
        sa.Column(
            "consolidated_vision_medium",
            sa.Text(),
            nullable=True,
            comment="66% summary of all active vision documents (consolidated)",
        ),
        sa.Column(
            "consolidated_vision_medium_tokens",
            sa.Integer(),
            nullable=True,
            comment="Token count of consolidated medium summary",
        ),
        sa.Column(
            "consolidated_vision_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hash of aggregated vision documents (for change detection)",
        ),
        sa.Column(
            "consolidated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when consolidated summaries were last generated",
        ),
        sa.Column("core_features", sa.Text(), nullable=True),
        sa.Column(
            "extraction_custom_instructions",
            sa.Text(),
            nullable=True,
            comment="Custom instructions appended to AI vision document extraction prompt",
        ),
        sa.Column(
            "brand_guidelines", sa.Text(), nullable=True, comment="Brand & design guidelines for frontend-facing agents"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "target_platforms <@ ARRAY['windows', 'linux', 'macos', 'android', 'ios', 'web', 'all']::VARCHAR[]",
            name="ck_product_target_platforms_valid",
        ),
        sa.CheckConstraint(
            "NOT ('all' = ANY(target_platforms) AND array_length(target_platforms, 1) > 1)",
            name="ck_product_target_platforms_all_exclusive",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_product_tenant", "products", ["tenant_key"], unique=False)
    op.create_index("idx_product_org_id", "products", ["org_id"], unique=False)
    op.create_index("idx_product_name", "products", ["name"], unique=False)
    op.create_index("idx_product_memory_gin", "products", ["product_memory"], unique=False, postgresql_using="gin")
    op.create_index(
        "idx_products_deleted_at",
        "products",
        ["deleted_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index("idx_products_consolidated_at", "products", ["consolidated_at"], unique=False)
    op.create_index(
        "idx_product_single_active_per_tenant",
        "products",
        ["tenant_key"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "project_types",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column(
            "abbreviation",
            sa.String(length=4),
            nullable=False,
            comment="2-4 uppercase letter abbreviation (e.g., BE, FE, API)",
        ),
        sa.Column(
            "label", sa.String(length=50), nullable=False, comment="Human-readable label (e.g., Backend, Frontend)"
        ),
        sa.Column("color", sa.String(length=7), nullable=False, comment="Hex color for UI display"),
        sa.Column("sort_order", sa.Integer(), nullable=True, comment="Display ordering in UI dropdowns"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key", "abbreviation", name="uq_project_type_abbr"),
    )
    op.create_index("idx_project_type_tenant", "project_types", ["tenant_key"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "alias",
            sa.String(length=6),
            nullable=False,
            comment="6-character alphanumeric project identifier (e.g., A1B2C3)",
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column(
            "staging_status",
            sa.String(length=50),
            nullable=True,
            comment="Staging workflow status: null (not staged), staging (in progress), or staging_complete",
        ),
        sa.Column(
            "project_type_id",
            sa.String(length=36),
            nullable=True,
            comment="FK to project_types for taxonomy classification",
        ),
        sa.Column(
            "series_number",
            sa.Integer(),
            nullable=True,
            comment="Sequential number within a project type (e.g., 1 in BE-0001)",
        ),
        sa.Column(
            "subseries",
            sa.String(length=1),
            nullable=True,
            comment="Single-letter subseries suffix (e.g., 'a' in BE-0001a)",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="First activation timestamp (only set once on first activation)",
        ),
        sa.Column(
            "implementation_launched_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when user clicked Implement button. NULL = staging only.",
        ),
        sa.Column(
            "ever_launched_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "First time this project EVER crossed the Implement gate. Set once, "
                "never overwritten by re-launch. Survives restage (audit-preserving); "
                "cleared only by reset_to_prestage (discard-everything rewind). Powers "
                "the BE-9085 pre-launch-workproduct detector's restage false-positive "
                "suppression. (BE-9085b, parity with ce_0075_projects_ever_launched_at.)"
            ),
        ),
        sa.Column(
            "paused_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when project was last paused/deactivated",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when project was soft deleted (NULL for active projects)",
        ),
        sa.Column(
            "orchestrator_summary",
            sa.Text(),
            nullable=True,
            comment="AI-generated final summary of project outcomes and deliverables",
        ),
        sa.Column(
            "closeout_prompt",
            sa.Text(),
            nullable=True,
            comment="Prompt template used by orchestrator for closeout generation",
        ),
        sa.Column(
            "closeout_executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when closeout workflow was executed",
        ),
        sa.Column(
            "closeout_checklist",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Structured checklist of closeout tasks (JSONB array)",
        ),
        sa.Column(
            "execution_mode",
            sa.String(length=20),
            nullable=True,
            comment=(
                "Execution mode: 'multi_terminal' | 'claude_code_cli' | 'codex_cli' | 'gemini_cli'; "
                "NULL = not yet selected (NULL-state redesign; see ce_0043). No server default."
            ),
        ),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column("early_termination", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("auto_checkin_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_checkin_interval", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether project is hidden from default list view",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_type_id"], ["project_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_project_tenant", "projects", ["tenant_key"], unique=False)
    op.create_index("idx_project_status", "projects", ["status"], unique=False)
    op.create_index(
        "idx_projects_deleted_at",
        "projects",
        ["deleted_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "idx_projects_closeout_executed",
        "projects",
        ["closeout_executed_at"],
        unique=False,
        postgresql_where=sa.text("closeout_executed_at IS NOT NULL"),
    )
    op.create_index(
        "idx_project_single_active_per_product",
        "projects",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(op.f("ix_projects_alias"), "projects", ["alias"], unique=True)
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_project_taxonomy_active "
            "ON projects (tenant_key, product_id, project_type_id, series_number, subseries) "
            "NULLS NOT DISTINCT "
            "WHERE deleted_at IS NULL"
        )
    )

    op.create_table(
        "mcp_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=True),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column(
            "session_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="MCP protocol state: client_info, capabilities, tool_call_history",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_accessed", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_mcp_sessions_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_mcp_session_api_key", "mcp_sessions", ["api_key_id"], unique=False)
    op.create_index("idx_mcp_session_tenant", "mcp_sessions", ["tenant_key"], unique=False)
    op.create_index("idx_mcp_session_user", "mcp_sessions", ["user_id"], unique=False)
    op.create_index("idx_mcp_session_last_accessed", "mcp_sessions", ["last_accessed"], unique=False)
    op.create_index("idx_mcp_session_cleanup", "mcp_sessions", ["expires_at", "last_accessed"], unique=False)
    op.create_index("idx_mcp_session_data_gin", "mcp_sessions", ["session_data"], unique=False, postgresql_using="gin")
    op.create_index(op.f("ix_mcp_sessions_session_id"), "mcp_sessions", ["session_id"], unique=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column(
            "org_id", sa.String(length=36), nullable=True, comment="Organization for org-level tasks (Handover 0424)"
        ),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("parent_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("converted_to_project_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("estimated_effort", sa.Float(), nullable=True),
        sa.Column("actual_effort", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["converted_to_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_task_org_id", "tasks", ["org_id"], unique=False)
    op.create_index("idx_task_product", "tasks", ["product_id"], unique=False)
    op.create_index("idx_task_project", "tasks", ["project_id"], unique=False)
    op.create_index("idx_task_status", "tasks", ["status"], unique=False)
    op.create_index("idx_task_priority", "tasks", ["priority"], unique=False)
    op.create_index("idx_task_created_by_user", "tasks", ["created_by_user_id"], unique=False)
    op.create_index("idx_task_tenant_created_user", "tasks", ["tenant_key", "created_by_user_id"], unique=False)
    op.create_index("idx_task_converted_to_project", "tasks", ["converted_to_project_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("message_type", sa.String(length=50), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("backoff_seconds", sa.Integer(), nullable=True),
        sa.Column("circuit_breaker_status", sa.String(length=20), nullable=True),
        sa.Column("from_agent_id", sa.String(length=36), nullable=True),
        sa.Column("from_display_name", sa.String(length=255), nullable=True),
        sa.Column("auto_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "requires_action",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="True if recipient must take action. False for informational messages.",
        ),
        sa.Column("loop_interval_minutes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_message_project", "messages", ["project_id"], unique=False)
    op.create_index("idx_message_status", "messages", ["status"], unique=False)
    op.create_index("idx_message_priority", "messages", ["priority"], unique=False)
    op.create_index("idx_message_created", "messages", ["created_at"], unique=False)

    op.create_table(
        "vision_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column(
            "document_name",
            sa.String(length=255),
            nullable=False,
            comment="User-friendly document name (e.g., 'Product Architecture', 'API Design')",
        ),
        sa.Column(
            "document_type",
            sa.String(length=50),
            nullable=False,
            comment="Document category: vision, architecture, features, setup, api, testing, deployment, custom",
        ),
        sa.Column(
            "vision_path",
            sa.String(length=500),
            nullable=True,
            comment="File path to vision document (file-based or hybrid storage)",
        ),
        sa.Column("vision_document", sa.Text(), nullable=True, comment="Inline vision text (inline or hybrid storage)"),
        sa.Column(
            "storage_type", sa.String(length=20), nullable=False, comment="Storage mode: 'file', 'inline', or 'hybrid'"
        ),
        sa.Column(
            "chunked", sa.Boolean(), nullable=False, comment="Has document been chunked into mcp_context_index for RAG"
        ),
        sa.Column("chunk_count", sa.Integer(), nullable=False, comment="Number of chunks created for this document"),
        sa.Column("total_tokens", sa.Integer(), nullable=True, comment="Estimated total tokens in document"),
        sa.Column(
            "file_size",
            sa.BigInteger(),
            nullable=True,
            comment="Original file size in bytes (NULL for inline content without file)",
        ),
        sa.Column(
            "is_summarized", sa.Boolean(), nullable=False, comment="Has document been summarized using LSA algorithm"
        ),
        sa.Column(
            "original_token_count",
            sa.Integer(),
            nullable=True,
            comment="Original document token count before summarization",
        ),
        sa.Column(
            "summary_light",
            sa.Text(),
            nullable=True,
            comment="Light summary (~33% of original, ~13K tokens for 40K doc)",
        ),
        sa.Column(
            "summary_medium",
            sa.Text(),
            nullable=True,
            comment="Medium summary (~66% of original, ~26K tokens for 40K doc)",
        ),
        sa.Column("summary_light_tokens", sa.Integer(), nullable=True, comment="Actual token count in light summary"),
        sa.Column("summary_medium_tokens", sa.Integer(), nullable=True, comment="Actual token count in medium summary"),
        sa.Column(
            "version", sa.String(length=50), nullable=False, comment="Document version using semantic versioning"
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hash of document content for change detection",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            comment="Active documents are used for context; inactive are archived",
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, comment="Display order in UI (lower numbers first)"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Additional metadata: author, tags, source_url, etc.",
        ),
        sa.CheckConstraint("storage_type IN ('file', 'inline', 'hybrid')", name="ck_vision_doc_storage_type"),
        sa.CheckConstraint(
            "document_type IN ('vision', 'architecture', 'features', 'setup', 'api', 'testing', 'deployment', 'custom')",
            name="ck_vision_doc_document_type",
        ),
        sa.CheckConstraint(
            "(storage_type = 'file' AND vision_path IS NOT NULL) OR (storage_type = 'inline' AND vision_document IS NOT NULL) OR (storage_type = 'hybrid' AND vision_path IS NOT NULL AND vision_document IS NOT NULL)",
            name="ck_vision_doc_storage_consistency",
        ),
        sa.CheckConstraint("chunk_count >= 0", name="ck_vision_doc_chunk_count"),
        sa.CheckConstraint(
            "(chunked = false AND chunk_count = 0) OR (chunked = true AND chunk_count > 0)",
            name="ck_vision_doc_chunked_consistency",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "document_name", name="uq_vision_doc_product_name"),
    )
    op.create_index("idx_vision_doc_type", "vision_documents", ["document_type"], unique=False)
    op.create_index("idx_vision_doc_active", "vision_documents", ["is_active"], unique=False)
    op.create_index("idx_vision_doc_chunked", "vision_documents", ["chunked"], unique=False)
    op.create_index("idx_vision_doc_tenant_product", "vision_documents", ["tenant_key", "product_id"], unique=False)
    op.create_index("idx_vision_doc_product_type", "vision_documents", ["product_id", "document_type"], unique=False)
    op.create_index(
        "idx_vision_doc_product_active", "vision_documents", ["product_id", "is_active", "display_order"], unique=False
    )

    op.create_table(
        "mcp_context_index",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column(
            "vision_document_id",
            sa.String(length=36),
            nullable=True,
            comment="Link to specific vision document (NULL for legacy product-level chunks)",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=True,
            comment="Optional LLM-generated summary (NULL for Phase 1 non-LLM chunking)",
        ),
        sa.Column(
            "keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Array of keyword strings extracted via regex or LLM",
        ),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column(
            "chunk_order", sa.Integer(), nullable=True, comment="Sequential chunk number for maintaining document order"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column(
            "searchable_vector",
            postgresql.TSVECTOR(),
            nullable=True,
            comment="Full-text search vector for fast keyword lookup",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vision_document_id"], ["vision_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id"),
    )
    op.create_index("idx_mcp_context_tenant_product", "mcp_context_index", ["tenant_key", "product_id"], unique=False)
    op.create_index(
        "idx_mcp_context_searchable", "mcp_context_index", ["searchable_vector"], unique=False, postgresql_using="gin"
    )
    op.create_index("idx_mcp_context_chunk_id", "mcp_context_index", ["chunk_id"], unique=False)
    op.create_index("idx_mcp_context_vision_doc", "mcp_context_index", ["vision_document_id"], unique=False)
    op.create_index(
        "idx_mcp_context_product_vision_doc", "mcp_context_index", ["product_id", "vision_document_id"], unique=False
    )

    op.create_table(
        "product_memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False, comment="Tenant isolation key"),
        sa.Column("product_id", sa.String(length=36), nullable=False, comment="Parent product (CASCADE on delete)"),
        sa.Column(
            "project_id",
            sa.String(length=36),
            nullable=True,
            comment="Source project (SET NULL on delete - preserves history)",
        ),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="Sequence number within product (1-based)"),
        sa.Column(
            "entry_type",
            sa.String(length=50),
            nullable=False,
            comment="Entry type: project_closeout, project_completion, handover_closeout, session_handover",
        ),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            comment="Source tool: closeout_v1, write_360_memory_v1, migration_backfill",
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, comment="When the entry was created"),
        sa.Column("project_name", sa.String(length=255), nullable=True, comment="Project name at time of entry"),
        sa.Column("summary", sa.Text(), nullable=True, comment="2-3 paragraph summary of work accomplished"),
        sa.Column(
            "key_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            comment="List of key achievements",
        ),
        sa.Column(
            "decisions_made",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            comment="List of architectural/design decisions",
        ),
        sa.Column(
            "git_commits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            comment="List of git commit objects with sha, message, author",
        ),
        sa.Column(
            "deliverables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            comment="List of files/artifacts delivered",
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            comment="Metrics dict (test_coverage, etc.)",
        ),
        sa.Column("priority", sa.Integer(), server_default="3", comment="Priority level 1-5"),
        sa.Column("significance_score", sa.Float(), server_default="0.5", comment="Significance score 0.0-1.0"),
        sa.Column("token_estimate", sa.Integer(), nullable=True, comment="Estimated tokens for this entry"),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            comment="List of tags for categorization",
        ),
        sa.Column(
            "author_job_id", sa.String(length=36), nullable=True, comment="Job ID of agent that wrote this entry"
        ),
        sa.Column("author_name", sa.String(length=255), nullable=True, comment="Name of agent that wrote this entry"),
        sa.Column(
            "author_type",
            sa.String(length=50),
            nullable=True,
            comment="Type of agent (orchestrator, implementer, etc.)",
        ),
        sa.Column(
            "deleted_by_user",
            sa.Boolean(),
            server_default="false",
            comment="True if source project was deleted by user",
        ),
        sa.Column(
            "user_deleted_at", sa.DateTime(timezone=True), nullable=True, comment="When the source project was deleted"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
            comment="When this row was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
            comment="When this row was last updated",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("product_id", "sequence", name="uq_product_sequence"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pme_tenant_product", "product_memory_entries", ["tenant_key", "product_id"])
    op.create_index(
        "idx_pme_project", "product_memory_entries", ["project_id"], postgresql_where=sa.text("project_id IS NOT NULL")
    )
    op.create_index(
        "idx_pme_tenant_timestamp",
        "product_memory_entries",
        ["tenant_key", sa.text("timestamp DESC")],
    )
    op.create_index("idx_pme_type", "product_memory_entries", ["entry_type"])
    op.create_index(
        "idx_pme_deleted",
        "product_memory_entries",
        ["deleted_by_user"],
        postgresql_where=sa.text("deleted_by_user = true"),
    )

    op.create_table(
        "agent_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            nullable=True,
            comment="Organization for org-level templates (Handover 0424)",
        ),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), server_default="role", nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column(
            "system_instructions",
            sa.Text(),
            nullable=False,
            comment="Protected MCP coordination instructions (non-editable by users)",
        ),
        sa.Column(
            "user_instructions", sa.Text(), nullable=True, comment="User-customizable role-specific guidance (editable)"
        ),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("behavioral_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool", sa.String(length=50), nullable=False),
        sa.Column("cli_tool", sa.String(length=20), nullable=False),
        sa.Column("background_color", sa.String(length=7), nullable=True),
        sa.Column("model", sa.String(length=20), nullable=True),
        sa.Column("tools", sa.String(length=50), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("avg_generation_ms", sa.Float(), nullable=True),
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("user_managed_export", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key", "name", "version", name="uq_template_tenant_name_version"),
    )
    op.create_index("idx_template_tenant", "agent_templates", ["tenant_key"], unique=False)
    op.create_index("idx_template_org_id", "agent_templates", ["org_id"], unique=False)
    op.create_index("idx_template_category", "agent_templates", ["category"], unique=False)
    op.create_index("idx_template_role", "agent_templates", ["role"], unique=False)
    op.create_index("idx_template_active", "agent_templates", ["is_active"], unique=False)
    op.create_index("idx_template_tool", "agent_templates", ["tool"], unique=False)

    op.create_table(
        "template_archives",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column("system_instructions", sa.Text(), nullable=True),
        sa.Column("user_instructions", sa.Text(), nullable=True),
        sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("behavioral_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("archive_reason", sa.String(length=255), nullable=True),
        sa.Column("archive_type", sa.String(length=20), nullable=True),
        sa.Column("archived_by", sa.String(length=100), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("usage_count_at_archive", sa.Integer(), nullable=True),
        sa.Column("avg_generation_ms_at_archive", sa.Float(), nullable=True),
        sa.Column("is_restorable", sa.Boolean(), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["agent_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_archive_tenant", "template_archives", ["tenant_key"], unique=False)
    op.create_index("idx_archive_template", "template_archives", ["template_id"], unique=False)
    op.create_index("idx_archive_product", "template_archives", ["product_id"], unique=False)
    op.create_index("idx_archive_version", "template_archives", ["version"], unique=False)
    op.create_index("idx_archive_date", "template_archives", ["archived_at"], unique=False)

    op.create_table(
        "template_usage_stats",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("variables_used", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("augmentations_applied", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_completed", sa.Boolean(), nullable=True),
        sa.Column("agent_success_rate", sa.Float(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["agent_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_usage_tenant", "template_usage_stats", ["tenant_key"], unique=False)
    op.create_index("idx_usage_template", "template_usage_stats", ["template_id"], unique=False)
    op.create_index("idx_usage_project", "template_usage_stats", ["project_id"], unique=False)
    op.create_index("idx_usage_date", "template_usage_stats", ["used_at"], unique=False)

    op.create_table(
        "agent_jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=50), nullable=False),
        sa.Column(
            "project_id", sa.String(length=36), nullable=True, comment="Project this job belongs to (Handover 0062)"
        ),
        sa.Column("mission", sa.Text(), nullable=False, comment="Agent mission/instructions"),
        sa.Column(
            "job_type",
            sa.String(length=100),
            nullable=False,
            comment="Job type: orchestrator, analyzer, implementer, tester, etc.",
        ),
        sa.Column("status", sa.String(length=50), nullable=False, comment="Job status: active, completed, cancelled"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "job_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Job-level metadata (field priorities, depth config, etc.)",
        ),
        sa.Column(
            "template_id", sa.String(length=36), nullable=True, comment="Template used to create this job (if any)"
        ),
        sa.Column(
            "phase",
            sa.Integer(),
            nullable=True,
            comment="Execution phase for multi-terminal ordering (1=first, same=parallel)",
        ),
        sa.CheckConstraint("status IN ('active', 'completed', 'cancelled')", name="ck_agent_job_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["agent_templates.id"]),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("idx_agent_jobs_project", "agent_jobs", ["project_id"], unique=False)
    op.create_index("idx_agent_jobs_tenant_project", "agent_jobs", ["tenant_key", "project_id"], unique=False)
    op.create_index("idx_agent_jobs_status", "agent_jobs", ["status"], unique=False)

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(length=36), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False, comment="Foreign key to parent AgentJob"),
        sa.Column("tenant_key", sa.String(length=50), nullable=False),
        sa.Column(
            "agent_display_name", sa.String(length=100), nullable=False, comment="Human-readable display name for UI"
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            comment="Execution status: waiting, working, blocked, complete, silent, decommissioned",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "spawned_by",
            sa.String(length=36),
            nullable=True,
            comment="Agent ID of parent executor (clear: agent, not job)",
        ),
        sa.Column("progress", sa.Integer(), nullable=False, comment="Execution completion progress (0-100%)"),
        sa.Column("current_task", sa.Text(), nullable=True, comment="Description of current task"),
        sa.Column(
            "block_reason",
            sa.Text(),
            nullable=True,
            comment="Explanation of why execution is blocked (NULL if not blocked)",
        ),
        sa.Column(
            "health_status",
            sa.String(length=20),
            nullable=False,
            comment="Health state: unknown, healthy, warning, critical, timeout",
        ),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_failure_count", sa.Integer(), nullable=False),
        sa.Column(
            "last_progress_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of last progress update from agent",
        ),
        sa.Column(
            "last_message_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of last message queue check",
        ),
        sa.Column(
            "mission_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when agent first fetched mission",
        ),
        sa.Column(
            "tool_type",
            sa.String(length=20),
            nullable=False,
            comment="AI coding tool assigned (claude-code, codex, gemini, universal)",
        ),
        sa.Column(
            "messages_sent_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Count of outbound messages sent by this agent",
        ),
        sa.Column(
            "messages_waiting_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Count of inbound messages waiting to be read",
        ),
        sa.Column(
            "messages_read_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Count of inbound messages that have been acknowledged/read",
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Structured completion result from agent (summary, artifacts, commits)",
        ),
        sa.Column(
            "accumulated_duration_seconds",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="Total working time across reactivation cycles (seconds)",
        ),
        sa.Column(
            "reactivation_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of times this agent has been reactivated after completion",
        ),
        sa.Column("agent_name", sa.String(length=255), nullable=True, comment="Human-readable display name for UI"),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Heartbeat timestamp for agent activity tracking",
        ),
        sa.Column(
            "project_phase",
            sa.String(length=20),
            nullable=False,
            server_default="implementation",
            comment=(
                "Lifecycle phase this orchestrator execution belongs to: "
                "'staging' or 'implementation'. Set at execution creation."
            ),
        ),
        sa.Column(
            "working_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Anchored on first transition INTO 'working'. Read by "
                "AgentExecution.duration_seconds; freezes on complete/closed."
            ),
        ),
        sa.CheckConstraint(
            "status IN ('waiting', 'working', 'blocked', 'complete', 'closed', 'silent', 'decommissioned', 'idle', 'sleeping')",
            name="ck_agent_execution_status",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_agent_execution_progress_range"),
        sa.CheckConstraint(
            "tool_type IN ('claude-code', 'codex', 'gemini', 'universal')", name="ck_agent_execution_tool_type"
        ),
        sa.CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'warning', 'critical', 'timeout')",
            name="ck_agent_execution_health_status",
        ),
        sa.CheckConstraint(
            "project_phase IN ('staging', 'implementation')",
            name="ck_agent_execution_project_phase",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["agent_jobs.job_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agent_executions_job", "agent_executions", ["job_id"], unique=False)
    op.create_index("idx_agent_executions_status", "agent_executions", ["status"], unique=False)
    op.create_index("idx_agent_executions_health", "agent_executions", ["health_status"], unique=False)
    op.create_index("idx_agent_executions_last_progress", "agent_executions", ["last_progress_at"], unique=False)
    op.create_index("idx_agent_executions_agent_id", "agent_executions", ["agent_id"])

    op.create_table(
        "agent_todo_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False, comment="Foreign key to parent AgentJob"),
        sa.Column("tenant_key", sa.String(length=64), nullable=False),
        sa.Column("content", sa.String(length=255), nullable=False, comment="TODO item description/task text"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
            comment="Item status: pending, in_progress, completed, skipped",
        ),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="Display order (0-based index in agent TODO list)"),
        sa.Column(
            "todo_kind",
            sa.String(length=32),
            nullable=True,
            comment="Self-closeout kind (self_closeout|closeout_intent|chain_drive) or NULL for ordinary work",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'skipped')", name="ck_agent_todo_item_status"
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_agent_todo_item_sequence_positive"),
        sa.ForeignKeyConstraint(["job_id"], ["agent_jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_todo_items_tenant_status", "agent_todo_items", ["tenant_key", "status"], unique=False)
    op.create_index("idx_todo_items_job_sequence", "agent_todo_items", ["job_id", "sequence"], unique=False)

    op.create_table(
        "configurations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key", "key", name="uq_config_tenant_key"),
    )
    op.create_index("idx_config_category", "configurations", ["category"], unique=False)

    op.create_table(
        "git_commits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("commit_hash", sa.String(length=40), nullable=False),
        sa.Column("commit_message", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(length=100), nullable=False),
        sa.Column("author_email", sa.String(length=255), nullable=False),
        sa.Column("branch_name", sa.String(length=100), nullable=False),
        sa.Column("files_changed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("insertions", sa.Integer(), nullable=True),
        sa.Column("deletions", sa.Integer(), nullable=True),
        sa.Column("triggered_by", sa.String(length=50), nullable=True),
        sa.Column("commit_type", sa.String(length=50), nullable=True),
        sa.Column("push_status", sa.String(length=20), nullable=True),
        sa.Column("push_error", sa.Text(), nullable=True),
        sa.Column("webhook_triggered", sa.Boolean(), nullable=True),
        sa.Column("webhook_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("push_status IN ('pending', 'pushed', 'failed')", name="ck_git_commit_push_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("commit_hash"),
    )
    op.create_index("idx_git_commit_tenant", "git_commits", ["tenant_key"], unique=False)
    op.create_index("idx_git_commit_product", "git_commits", ["product_id"], unique=False)
    op.create_index("idx_git_commit_project", "git_commits", ["project_id"], unique=False)
    op.create_index("idx_git_commit_hash", "git_commits", ["commit_hash"], unique=False)
    op.create_index("idx_git_commit_date", "git_commits", ["committed_at"], unique=False)
    op.create_index("idx_git_commit_trigger", "git_commits", ["triggered_by"], unique=False)

    op.create_table(
        "setup_state",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("database_initialized", sa.Boolean(), nullable=False),
        sa.Column("database_initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_version", sa.String(length=20), nullable=True),
        sa.Column("database_version", sa.String(length=20), nullable=True),
        sa.Column("python_version", sa.String(length=20), nullable=True),
        sa.Column("node_version", sa.String(length=20), nullable=True),
        sa.Column(
            "first_admin_created",
            sa.Boolean(),
            nullable=False,
            comment="True after first admin account created - prevents duplicate admin creation attacks",
        ),
        sa.Column(
            "first_admin_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when first admin account was created",
        ),
        sa.Column(
            "features_configured",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Nested dict of configured features: {database: true, api: {enabled: true, port: 7272}}",
        ),
        sa.Column(
            "tools_enabled",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Array of enabled MCP tool names",
        ),
        sa.Column(
            "config_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Snapshot of config.yaml at setup completion",
        ),
        sa.Column("validation_passed", sa.Boolean(), nullable=False),
        sa.Column(
            "validation_failures",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Array of validation failure messages",
        ),
        sa.Column(
            "validation_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Array of validation warning messages",
        ),
        sa.Column("last_validation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("installer_version", sa.String(length=20), nullable=True),
        sa.Column(
            "install_mode",
            sa.String(length=20),
            nullable=True,
            comment="Installation mode: localhost, server, lan, wan",
        ),
        sa.Column("install_path", sa.Text(), nullable=True, comment="Installation directory path"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "setup_version IS NULL OR setup_version ~ '^[0-9]+\\.[0-9]+\\.[0-9]+(-[a-zA-Z0-9\\.\\-]+)?$'",
            name="ck_setup_version_format",
        ),
        sa.CheckConstraint(
            "database_version IS NULL OR database_version ~ '^[0-9]+(\\.([0-9]+|[0-9]+\\.[0-9]+))?$'",
            name="ck_database_version_format",
        ),
        sa.CheckConstraint(
            "install_mode IS NULL OR install_mode IN ('localhost', 'server', 'lan', 'wan')",
            name="ck_install_mode_values",
        ),
        sa.CheckConstraint(
            "(database_initialized = false) OR (database_initialized = true AND database_initialized_at IS NOT NULL)",
            name="ck_database_initialized_at_required",
        ),
        sa.CheckConstraint(
            "(first_admin_created = false) OR (first_admin_created = true AND first_admin_created_at IS NOT NULL)",
            name="ck_first_admin_created_at_required",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_setup_database_initialized", "setup_state", ["database_initialized"], unique=False)
    op.create_index("idx_setup_mode", "setup_state", ["install_mode"], unique=False)
    op.create_index(
        "idx_setup_features_gin", "setup_state", ["features_configured"], unique=False, postgresql_using="gin"
    )
    op.create_index("idx_setup_tools_gin", "setup_state", ["tools_enabled"], unique=False, postgresql_using="gin")
    op.create_index(
        "idx_setup_database_incomplete",
        "setup_state",
        ["tenant_key", "database_initialized"],
        unique=False,
        postgresql_where="database_initialized = false",
    )
    op.create_index(
        "idx_setup_fresh_install",
        "setup_state",
        ["tenant_key", "first_admin_created"],
        unique=False,
        postgresql_where="first_admin_created = false",
    )
    op.create_index(op.f("ix_setup_state_tenant_key"), "setup_state", ["tenant_key"], unique=True)
    op.create_index(op.f("ix_setup_state_first_admin_created"), "setup_state", ["first_admin_created"], unique=False)

    op.create_table(
        "settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("settings_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key", "category", name="uq_settings_tenant_category"),
    )
    op.create_index("idx_settings_category", "settings", ["category"], unique=False)

    op.create_table(
        "download_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(length=36), nullable=False, comment="UUID v4 token used in download URL"),
        sa.Column("tenant_key", sa.String(length=36), nullable=False, comment="Tenant key for multi-tenant isolation"),
        sa.Column(
            "download_type",
            sa.String(length=50),
            nullable=False,
            comment="Type of download: 'slash_commands', 'agent_templates'",
        ),
        sa.Column(
            "staging_status",
            sa.String(length=20),
            nullable=False,
            comment="Staging lifecycle status: pending|ready|failed",
        ),
        sa.Column("staging_error", sa.Text(), nullable=True, comment="Staging error details when status=failed"),
        sa.Column(
            "download_count", sa.Integer(), nullable=False, comment="Number of successful downloads for this token"
        ),
        sa.Column(
            "last_downloaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of most recent successful download",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Token expiry timestamp (15 minutes after creation)",
        ),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.CheckConstraint("download_type IN ('slash_commands', 'agent_templates')", name="ck_download_token_type"),
        sa.CheckConstraint("staging_status IN ('pending', 'ready', 'failed')", name="ck_download_token_staging_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_download_token_expires", "download_tokens", ["expires_at"], unique=False)
    op.create_index("idx_download_token_tenant_type", "download_tokens", ["tenant_key", "download_type"], unique=False)
    op.create_index(op.f("ix_download_tokens_token"), "download_tokens", ["token"], unique=True)

    op.create_table(
        "api_metrics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_api_calls", sa.Integer(), nullable=True),
        sa.Column("total_mcp_calls", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_api_metrics_tenant_date", "api_metrics", ["tenant_key", "date"], unique=False)
    op.create_index(op.f("ix_api_metrics_tenant_key"), "api_metrics", ["tenant_key"], unique=True)

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("code_challenge_method", sa.String(length=10), nullable=True),
        sa.Column("scope", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_oauth_code_tenant", "oauth_authorization_codes", ["tenant_key"], unique=False)
    op.create_index("idx_oauth_code_user", "oauth_authorization_codes", ["user_id"], unique=False)
    op.create_index("idx_oauth_code_expires", "oauth_authorization_codes", ["expires_at"], unique=False)
    op.create_index("idx_oauth_code_lookup", "oauth_authorization_codes", ["code", "tenant_key"], unique=False)
    op.create_index(op.f("ix_oauth_authorization_codes_code"), "oauth_authorization_codes", ["code"], unique=True)

    op.create_table(
        "message_recipients",
        sa.Column("id", sa.String(length=36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", "agent_id", name="uq_msg_recipient"),
    )
    op.create_index("idx_message_recipients_agent", "message_recipients", ["agent_id", "tenant_key"])

    op.create_table(
        "message_acknowledgments",
        sa.Column("id", sa.String(length=36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", "agent_id", name="uq_msg_ack"),
    )
    op.create_index("idx_message_acks_agent", "message_acknowledgments", ["agent_id", "tenant_key"])

    op.create_table(
        "message_completions",
        sa.Column("id", sa.String(length=36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", "agent_id", name="uq_msg_completion"),
    )
    op.create_index("idx_message_completions_agent", "message_completions", ["agent_id", "tenant_key"])

    op.create_table(
        "user_field_priorities",
        sa.Column("id", sa.String(length=36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "category", name="uq_user_field_priorities_user_category"),
    )
    op.create_index("idx_user_field_priorities_user", "user_field_priorities", ["user_id", "tenant_key"])

    op.create_table(
        "vision_document_summaries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("vision_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("ratio", sa.Numeric(3, 2), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("tokens_original", sa.Integer(), nullable=False),
        sa.Column("tokens_summary", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_vds_lookup", "vision_document_summaries", ["tenant_key", "document_id", "source", "ratio"])
    op.create_index("idx_vds_product", "vision_document_summaries", ["tenant_key", "product_id"])

    op.create_table(
        "product_tech_stacks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(length=36),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("programming_languages", sa.Text(), nullable=True),
        sa.Column("frontend_frameworks", sa.Text(), nullable=True),
        sa.Column("backend_frameworks", sa.Text(), nullable=True),
        sa.Column("databases_storage", sa.Text(), nullable=True),
        sa.Column("infrastructure", sa.Text(), nullable=True),
        sa.Column("dev_tools", sa.Text(), nullable=True),
        sa.Column("target_windows", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("target_linux", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("target_macos", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("target_android", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("target_ios", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("target_cross_platform", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_product_tech_stacks_tenant", "product_tech_stacks", ["tenant_key"])

    op.create_table(
        "product_architectures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(length=36),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("primary_pattern", sa.Text(), nullable=True),
        sa.Column("design_patterns", sa.Text(), nullable=True),
        sa.Column("api_style", sa.Text(), nullable=True),
        sa.Column("architecture_notes", sa.Text(), nullable=True),
        sa.Column("coding_conventions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_product_architectures_tenant", "product_architectures", ["tenant_key"])

    op.create_table(
        "product_test_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(length=36),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("quality_standards", sa.Text(), nullable=True),
        sa.Column("test_strategy", sa.String(length=50), nullable=True),
        sa.Column("coverage_target", sa.Integer(), server_default=sa.text("80")),
        sa.Column("testing_frameworks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_product_test_configs_tenant", "product_test_configs", ["tenant_key"])

    op.create_table(
        "product_agent_assignments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "product_id",
            sa.String(36),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("agent_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tenant_key", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "template_id", name="uq_product_template_assignment"),
    )
    op.create_index("idx_assignment_tenant", "product_agent_assignments", ["tenant_key"])
    op.create_index("idx_assignment_template", "product_agent_assignments", ["template_id"])
    op.create_index("idx_assignment_active", "product_agent_assignments", ["is_active"])


def downgrade() -> None:

    op.drop_table("product_agent_assignments")
    op.drop_table("product_test_configs")
    op.drop_table("product_architectures")
    op.drop_table("product_tech_stacks")
    op.drop_table("vision_document_summaries")
    op.drop_table("user_field_priorities")
    op.drop_table("message_completions")
    op.drop_table("message_acknowledgments")
    op.drop_table("message_recipients")

    op.drop_table("oauth_authorization_codes")
    op.drop_table("api_metrics")
    op.drop_table("download_tokens")
    op.drop_table("settings")
    op.drop_table("setup_state")
    op.drop_table("git_commits")
    op.drop_table("configurations")
    op.drop_table("agent_todo_items")
    op.drop_table("agent_executions")
    op.drop_table("agent_jobs")
    op.drop_table("template_usage_stats")
    op.drop_table("template_archives")
    op.drop_table("agent_templates")
    op.drop_table("product_memory_entries")
    op.drop_table("mcp_context_index")
    op.drop_table("vision_documents")
    op.drop_table("messages")
    op.drop_table("tasks")
    op.drop_table("mcp_sessions")
    op.drop_table("projects")
    op.drop_table("project_types")
    op.drop_table("products")
    op.drop_table("api_key_ip_log")
    op.drop_table("api_keys")
    op.drop_table("org_memberships")
    op.drop_table("users")
    op.drop_table("organizations")
