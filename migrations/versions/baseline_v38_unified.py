# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "baseline_v38"
down_revision: str | Sequence[str] | None = "ce_0077_sequence_run_reviewed_project_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    current_len = conn.execute(
        sa.text(
            "SELECT character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'alembic_version' "
            "AND column_name = 'version_num'"
        )
    ).scalar()
    if current_len is not None and current_len < 64:
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    op.execute(
        """
        DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_status') THEN
            CREATE TYPE project_status AS ENUM ('inactive', 'active', 'completed', 'cancelled', 'terminated', 'deleted', 'superseded', 'parked');
        END IF; END $$;
        """
    )

    _existing_tables = set(sa.inspect(conn).get_table_names())

    if "agent_executions" not in _existing_tables:
        op.create_table(
            "agent_executions",
            sa.Column("id", sa.String(length=36), server_default=sa.text("(gen_random_uuid())::text"), nullable=False),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False, comment="Foreign key to parent AgentJob"),
            sa.Column("tenant_key", sa.String(length=50), nullable=False),
            sa.Column(
                "agent_display_name",
                sa.String(length=100),
                nullable=False,
                comment="Human-readable display name for UI",
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
                server_default=sa.text("0"),
                nullable=False,
                comment="Count of outbound messages sent by this agent",
            ),
            sa.Column(
                "messages_waiting_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
                comment="Count of inbound messages waiting to be read",
            ),
            sa.Column(
                "messages_read_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
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
                sa.Float(precision=53),
                server_default=sa.text("'0'::double precision"),
                nullable=False,
                comment="Total working time across reactivation cycles (seconds)",
            ),
            sa.Column(
                "reactivation_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
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
                server_default=sa.text("'implementation'::character varying"),
                nullable=False,
                comment="Lifecycle phase this orchestrator execution belongs to: 'staging' or 'implementation'. Set at execution creation.",
            ),
            sa.Column(
                "working_started_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Anchored on first transition INTO 'working'. Read by AgentExecution.duration_seconds; freezes on complete/closed.",
            ),
            sa.CheckConstraint(
                "health_status IN ('unknown', 'healthy', 'warning', 'critical', 'timeout')",
                name="ck_agent_execution_health_status",
            ),
            sa.CheckConstraint("(((progress >= 0) AND (progress <= 100)))", name="ck_agent_execution_progress_range"),
            sa.CheckConstraint(
                "project_phase IN ('staging', 'implementation')", name="ck_agent_execution_project_phase"
            ),
            sa.CheckConstraint(
                "status IN ('waiting', 'working', 'blocked', 'complete', 'closed', 'silent', 'decommissioned', 'idle', 'sleeping', 'awaiting_user', 'staged')",
                name="ck_agent_execution_status",
            ),
            sa.CheckConstraint(
                "tool_type IN ('claude-code', 'codex', 'gemini', 'antigravity', 'universal')",
                name="ck_agent_execution_tool_type",
            ),
            sa.PrimaryKeyConstraint("id", name="agent_executions_pkey"),
        )

    if "agent_jobs" not in _existing_tables:
        op.create_table(
            "agent_jobs",
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=50), nullable=False),
            sa.Column(
                "project_id", sa.String(length=36), nullable=True, comment="Project this job belongs to (Handover 0062)"
            ),
            sa.Column("mission", sa.Text(), nullable=True, comment="Agent mission/instructions"),
            sa.Column(
                "job_type",
                sa.String(length=100),
                nullable=False,
                comment="Job type: orchestrator, analyzer, implementer, tester, etc.",
            ),
            sa.Column(
                "status", sa.String(length=50), nullable=False, comment="Job status: active, completed, cancelled"
            ),
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
            sa.PrimaryKeyConstraint("job_id", name="agent_jobs_pkey"),
        )

    if "agent_templates" not in _existing_tables:
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
            sa.Column(
                "category", sa.String(length=50), server_default=sa.text("'role'::character varying"), nullable=False
            ),
            sa.Column("role", sa.String(length=50), nullable=True),
            sa.Column(
                "system_instructions",
                sa.Text(),
                nullable=False,
                comment="Protected MCP coordination instructions (non-editable by users)",
            ),
            sa.Column(
                "user_instructions",
                sa.Text(),
                nullable=True,
                comment="User-customizable role-specific guidance (editable)",
            ),
            sa.Column("variables", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("behavioral_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("success_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("tool", sa.String(length=50), nullable=False),
            sa.Column("cli_tool", sa.String(length=20), nullable=False),
            sa.Column("background_color", sa.String(length=7), nullable=True),
            sa.Column("model", sa.String(length=120), nullable=True),
            sa.Column("tools", sa.String(length=50), nullable=True),
            sa.Column("avg_generation_ms", sa.Float(precision=53), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("version", sa.String(length=20), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=True),
            sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("meta_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Timestamp when template was soft deleted (NULL for live templates)",
            ),
            sa.Column("effort", sa.String(length=120), nullable=False, server_default="inherit"),
            sa.PrimaryKeyConstraint("id", name="agent_templates_pkey"),
        )

    if "agent_todo_items" not in _existing_tables:
        op.create_table(
            "agent_todo_items",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False, comment="Foreign key to parent AgentJob"),
            sa.Column("tenant_key", sa.String(length=64), nullable=False),
            sa.Column("content", sa.String(length=255), nullable=False, comment="TODO item description/task text"),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default=sa.text("'pending'::character varying"),
                nullable=False,
                comment="Item status: pending, in_progress, completed, skipped",
            ),
            sa.Column(
                "sequence", sa.Integer(), nullable=False, comment="Display order (0-based index in agent TODO list)"
            ),
            sa.Column(
                "todo_kind",
                sa.String(length=32),
                nullable=True,
                comment="Self-closeout kind (self_closeout|closeout_intent|chain_drive) or NULL for ordinary work",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.CheckConstraint("((sequence >= 0))", name="ck_agent_todo_item_sequence_positive"),
            sa.CheckConstraint(
                "status IN ('pending', 'in_progress', 'completed', 'skipped')", name="ck_agent_todo_item_status"
            ),
            sa.PrimaryKeyConstraint("id", name="agent_todo_items_pkey"),
        )

    if "api_key_ip_log" not in _existing_tables:
        op.create_table(
            "api_key_ip_log",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("api_key_id", sa.String(length=36), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=False),
            sa.Column("request_count", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="api_key_ip_log_pkey"),
            sa.UniqueConstraint("api_key_id", "ip_address", name="uq_api_key_ip"),
        )

    if "api_keys" not in _existing_tables:
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
                "((((is_active = true) AND (revoked_at IS NULL)) OR (is_active = false)))",
                name="ck_apikey_revoked_consistency",
            ),
            sa.PrimaryKeyConstraint("id", name="api_keys_pkey"),
        )

    if "api_metrics" not in _existing_tables:
        op.create_table(
            "api_metrics",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("total_api_calls", sa.Integer(), nullable=True),
            sa.Column("total_mcp_calls", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="api_metrics_pkey"),
        )

    if "comm_participants" not in _existing_tables:
        op.create_table(
            "comm_participants",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("thread_id", sa.String(length=36), nullable=False),
            sa.Column("participant_id", sa.String(length=255), nullable=False),
            sa.Column("participant_type", sa.String(length=20), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("role", sa.String(length=50), nullable=True),
            sa.Column(
                "joined_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.Column("last_read_message_id", sa.String(length=36), nullable=True),
            sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "harness",
                sa.String(length=32),
                nullable=True,
                comment="BE-9289a: harness token stamped from the MCP handshake; never self-declared",
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="BE-9289a: last post/read/poll on this thread; drives the live-idle indicator",
            ),
            sa.Column(
                "self_reported_status",
                sa.String(length=20),
                nullable=True,
                comment="BE-9475: participant's own status claim; FALLBACK only -- agent_executions wins",
            ),
            sa.Column(
                "self_reported_status_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="BE-9475: when that claim was made; recorded for forensics, never aged out",
            ),
            sa.PrimaryKeyConstraint("id", name="comm_participants_pkey"),
            sa.UniqueConstraint("thread_id", "participant_id", name="uq_comm_participant"),
        )

    if "comm_threads" not in _existing_tables:
        op.create_table(
            "comm_threads",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("serial", sa.Integer(), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=True),
            sa.Column(
                "status", sa.String(length=50), server_default=sa.text("'open'::character varying"), nullable=False
            ),
            sa.Column("next_action_owner", sa.String(length=255), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=True),
            sa.Column("product_id", sa.String(length=36), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "sequence_run_id",
                sa.String(length=36),
                nullable=True,
                comment="BE-9291: the chain run this thread is the coordination hub for (NULL = not a hub)",
            ),
            sa.PrimaryKeyConstraint("id", name="comm_threads_pkey"),
            sa.UniqueConstraint("tenant_key", "serial", name="uq_comm_thread_serial"),
        )

    if "configurations" not in _existing_tables:
        op.create_table(
            "configurations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="configurations_pkey"),
            sa.UniqueConstraint("tenant_key", "key", name="uq_config_tenant_key"),
        )

    if "download_tokens" not in _existing_tables:
        op.create_table(
            "download_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=36), nullable=False, comment="UUID v4 token used in download URL"),
            sa.Column(
                "tenant_key", sa.String(length=36), nullable=False, comment="Tenant key for multi-tenant isolation"
            ),
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
            sa.Column(
                "staged_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="TSK-9210: when this token's ZIP was staged; anchors per-token staleness",
            ),
            sa.CheckConstraint(
                "staging_status IN ('pending', 'ready', 'failed')", name="ck_download_token_staging_status"
            ),
            sa.CheckConstraint(
                "download_type IN ('slash_commands', 'agent_templates', 'tenant_export')", name="ck_download_token_type"
            ),
            sa.PrimaryKeyConstraint("id", name="download_tokens_pkey"),
        )

    if "login_lockouts" not in _existing_tables:
        op.create_table(
            "login_lockouts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("identifier", sa.String(length=255), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=False),
            sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_failed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name="login_lockouts_pkey"),
            sa.UniqueConstraint("identifier", "ip_address", name="uq_login_lockout_identifier_ip"),
        )

    if "mcp_context_index" not in _existing_tables:
        op.create_table(
            "mcp_context_index",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
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
                "chunk_order",
                sa.Integer(),
                nullable=True,
                comment="Sequential chunk number for maintaining document order",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id", name="mcp_context_index_pkey"),
        )

    if "mcp_sessions" not in _existing_tables:
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
            sa.PrimaryKeyConstraint("id", name="mcp_sessions_pkey"),
        )

    if "message_acknowledgments" not in _existing_tables:
        op.create_table(
            "message_acknowledgments",
            sa.Column("id", sa.String(length=36), server_default=sa.text("(gen_random_uuid())::text"), nullable=False),
            sa.Column("message_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id", name="message_acknowledgments_pkey"),
            sa.UniqueConstraint("message_id", "agent_id", name="uq_msg_ack"),
        )

    if "message_completions" not in _existing_tables:
        op.create_table(
            "message_completions",
            sa.Column("id", sa.String(length=36), server_default=sa.text("(gen_random_uuid())::text"), nullable=False),
            sa.Column("message_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id", name="message_completions_pkey"),
            sa.UniqueConstraint("message_id", "agent_id", name="uq_msg_completion"),
        )

    if "message_recipients" not in _existing_tables:
        op.create_table(
            "message_recipients",
            sa.Column("id", sa.String(length=36), server_default=sa.text("(gen_random_uuid())::text"), nullable=False),
            sa.Column("message_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id", name="message_recipients_pkey"),
            sa.UniqueConstraint("message_id", "agent_id", name="uq_msg_recipient"),
        )

    if "messages" not in _existing_tables:
        op.create_table(
            "messages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("message_type", sa.String(length=50), nullable=True),
            sa.Column("subject", sa.String(length=255), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("priority", sa.String(length=20), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("from_agent_id", sa.String(length=64), nullable=True),
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
            sa.Column("thread_id", sa.String(length=36), nullable=True),
            sa.Column(
                "from_kind",
                sa.String(length=10),
                server_default=sa.text("'agent'"),
                nullable=False,
                comment="BE-9289a: author kind ('agent'|'user'), resolved server-side at post time",
            ),
            sa.PrimaryKeyConstraint("id", name="messages_pkey"),
        )

    if "notifications" not in _existing_tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("type", sa.String(length=100), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column(
                "payload",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("surface", sa.Text(), server_default=sa.text("'bell'::text"), nullable=False),
            sa.Column("role_filter", sa.Text(), nullable=True),
            sa.Column("cta_label", sa.Text(), nullable=True),
            sa.Column("cta_route", sa.Text(), nullable=True),
            sa.Column("dismissible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.CheckConstraint(
                "((surface = ANY (ARRAY['bell'::text, 'banner'::text, 'both'::text])))", name="ck_notifications_surface"
            ),
            sa.PrimaryKeyConstraint("id", name="notifications_pkey"),
        )

    if "oauth_authorization_codes" not in _existing_tables:
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
            sa.Column(
                "scope",
                sa.String(length=512),
                server_default=sa.text("'mcp:read mcp:write'::character varying"),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("resource", sa.String(length=2048), nullable=True),
            sa.PrimaryKeyConstraint("id", name="oauth_authorization_codes_pkey"),
        )

    if "oauth_refresh_tokens" not in _existing_tables:
        op.create_table(
            "oauth_refresh_tokens",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("family_id", sa.UUID(), nullable=False),
            sa.Column("client_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_key", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("aud", sa.Text(), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column(
                "origin_code_hash",
                sa.String(length=64),
                nullable=True,
                comment="SEC-9227b: sha256 hex of the auth code that minted this family; enables reuse-revocation",
            ),
            sa.PrimaryKeyConstraint("id", name="oauth_refresh_tokens_pkey"),
            sa.UniqueConstraint("token_hash", name="oauth_refresh_tokens_token_hash_key"),
        )

    if "oauth_revoked_tokens" not in _existing_tables:
        op.create_table(
            "oauth_revoked_tokens",
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column("token_type", sa.String(length=32), nullable=False),
            sa.Column("tenant_key", sa.String(length=64), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("jti", name="oauth_revoked_tokens_pkey"),
        )

    if "org_memberships" not in _existing_tables:
        op.create_table(
            "org_memberships",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("invited_by", sa.String(length=36), nullable=True),
            sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name="ck_membership_role"),
            sa.PrimaryKeyConstraint("id", name="org_memberships_pkey"),
            sa.UniqueConstraint("org_id", "user_id", name="uq_org_user"),
        )

    if "organizations" not in _existing_tables:
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column(
                "settings",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("org_setup_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="organizations_pkey"),
        )

    if "product_agent_assignments" not in _existing_tables:
        op.create_table(
            "product_agent_assignments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("template_id", sa.String(length=36), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="product_agent_assignments_pkey"),
            sa.UniqueConstraint("product_id", "template_id", name="uq_product_template_assignment"),
        )

    if "product_architectures" not in _existing_tables:
        op.create_table(
            "product_architectures",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("primary_pattern", sa.Text(), nullable=True),
            sa.Column("design_patterns", sa.Text(), nullable=True),
            sa.Column("api_style", sa.Text(), nullable=True),
            sa.Column("architecture_notes", sa.Text(), nullable=True),
            sa.Column("coding_conventions", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="product_architectures_pkey"),
            sa.UniqueConstraint("product_id", name="product_architectures_product_id_key"),
        )

    if "product_memory_entries" not in _existing_tables:
        op.create_table(
            "product_memory_entries",
            sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
                server_default=sa.text("'[]'::jsonb"),
                nullable=True,
                comment="List of key achievements",
            ),
            sa.Column(
                "decisions_made",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=True,
                comment="List of architectural/design decisions",
            ),
            sa.Column(
                "git_commits",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=True,
                comment="List of git commit objects with sha, message, author",
            ),
            sa.Column(
                "deliverables",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=True,
                comment="List of files/artifacts delivered",
            ),
            sa.Column(
                "metrics",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=True,
                comment="Metrics dict (test_coverage, etc.)",
            ),
            sa.Column(
                "priority", sa.Integer(), server_default=sa.text("3"), nullable=True, comment="Priority level 1-5"
            ),
            sa.Column(
                "significance_score",
                sa.Float(precision=53),
                server_default=sa.text("'0.5'::double precision"),
                nullable=True,
                comment="Significance score 0.0-1.0",
            ),
            sa.Column("token_estimate", sa.Integer(), nullable=True, comment="Estimated tokens for this entry"),
            sa.Column(
                "tags",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=True,
                comment="List of tags for categorization",
            ),
            sa.Column(
                "author_job_id", sa.String(length=36), nullable=True, comment="Job ID of agent that wrote this entry"
            ),
            sa.Column(
                "author_name", sa.String(length=255), nullable=True, comment="Name of agent that wrote this entry"
            ),
            sa.Column(
                "author_type",
                sa.String(length=50),
                nullable=True,
                comment="Type of agent (orchestrator, implementer, etc.)",
            ),
            sa.Column(
                "deleted_by_user",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=True,
                comment="True if source project was deleted by user",
            ),
            sa.Column(
                "user_deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="When the source project was deleted",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
                comment="When this row was created",
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
                comment="When this row was last updated",
            ),
            sa.PrimaryKeyConstraint("id", name="product_memory_entries_pkey"),
            sa.UniqueConstraint("product_id", "sequence", name="uq_product_sequence"),
        )

    if "product_tech_stacks" not in _existing_tables:
        op.create_table(
            "product_tech_stacks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("programming_languages", sa.Text(), nullable=True),
            sa.Column("frontend_frameworks", sa.Text(), nullable=True),
            sa.Column("backend_frameworks", sa.Text(), nullable=True),
            sa.Column("databases_storage", sa.Text(), nullable=True),
            sa.Column("infrastructure", sa.Text(), nullable=True),
            sa.Column("dev_tools", sa.Text(), nullable=True),
            sa.Column("target_windows", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("target_linux", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("target_macos", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("target_android", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("target_ios", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("target_cross_platform", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="product_tech_stacks_pkey"),
            sa.UniqueConstraint("product_id", name="product_tech_stacks_product_id_key"),
        )

    if "product_test_configs" not in _existing_tables:
        op.create_table(
            "product_test_configs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("quality_standards", sa.Text(), nullable=True),
            sa.Column("test_strategy", sa.String(length=50), nullable=True),
            sa.Column("coverage_target", sa.Integer(), server_default=sa.text("80"), nullable=True),
            sa.Column("testing_frameworks", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="product_test_configs_pkey"),
            sa.UniqueConstraint("product_id", name="product_test_configs_product_id_key"),
        )

    if "products" not in _existing_tables:
        op.create_table(
            "products",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column(
                "org_id",
                sa.String(length=36),
                nullable=True,
                comment="Organization that owns this product (Handover 0424)",
            ),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "project_path",
                sa.String(length=500),
                nullable=True,
                comment="File system path to product folder (required for agent export)",
            ),
            sa.Column(
                "quality_standards", sa.Text(), nullable=True, comment="Quality standards and testing expectations"
            ),
            sa.Column(
                "target_platforms",
                postgresql.ARRAY(sa.String()),
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
                comment="Shown as a tab in the product tab strip (FE-9524/D1). A new product is shown by default.",
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
                "brand_guidelines",
                sa.Text(),
                nullable=True,
                comment="Brand & design guidelines for frontend-facing agents",
            ),
            sa.Column(
                "vision_analysis_complete",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
                comment="True when all per-doc + product-aggregate summaries are populated. Gates project staging UX (BE-5118).",
            ),
            sa.CheckConstraint(
                "((NOT (('all'::text = ANY ((target_platforms)::text[])) AND (array_length(target_platforms, 1) > 1))))",
                name="ck_product_target_platforms_all_exclusive",
            ),
            sa.CheckConstraint(
                "((target_platforms <@ ARRAY['windows'::character varying, 'linux'::character varying, 'macos'::character varying, 'android'::character varying, 'ios'::character varying, 'web'::character varying, 'all'::character varying]))",
                name="ck_product_target_platforms_valid",
            ),
            sa.Column(
                "slug",
                sa.String(length=64),
                nullable=True,
                comment="BE-9385b: stable URL-safe short name qualifying exported agent filenames",
            ),
            sa.PrimaryKeyConstraint("id", name="products_pkey"),
        )

    if "projects" not in _existing_tables:
        op.create_table(
            "projects",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "alias",
                sa.String(length=6),
                nullable=False,
                comment="6-character alphanumeric project identifier (e.g., A1B2C3)",
            ),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("mission", sa.Text(), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "inactive",
                    "active",
                    "completed",
                    "cancelled",
                    "terminated",
                    "deleted",
                    "superseded",
                    "parked",
                    name="project_status",
                    create_type=False,
                ),
                server_default=sa.text("'inactive'::public.project_status"),
                nullable=False,
            ),
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
                "implementation_launched_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="Timestamp when user clicked Implement button. NULL = staging only.",
            ),
            sa.Column(
                "ever_launched_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="First time this project EVER crossed the Implement gate. Set once, never overwritten by re-launch. Survives restage (audit-preserving); cleared only by reset_to_prestage (discard-everything rewind). Powers the BE-9085 pre-launch-workproduct detector's restage false-positive suppression. (BE-9085b, parity with ce_0075_projects_ever_launched_at.)",
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
                comment="Execution mode: 'multi_terminal' | 'claude_code_cli' | 'codex_cli' | 'gemini_cli'; NULL = not yet selected (NULL-state redesign; see ce_0043). No server default.",
            ),
            sa.Column("cancellation_reason", sa.Text(), nullable=True),
            sa.Column("early_termination", sa.Boolean(), server_default=sa.text("false"), nullable=True),
            sa.Column("auto_checkin_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("auto_checkin_interval", sa.Integer(), server_default=sa.text("10"), nullable=False),
            sa.Column(
                "hidden",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
                comment="Whether project is hidden from default list view",
            ),
            sa.Column(
                "successor_project_id",
                sa.String(length=36),
                nullable=True,
                comment="FK to the project that supersedes this one (audit trail for replaced work)",
            ),
            sa.PrimaryKeyConstraint("id", name="projects_pkey"),
        )

    if "roadmap_items" not in _existing_tables:
        op.create_table(
            "roadmap_items",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("roadmap_id", sa.String(length=36), nullable=False),
            sa.Column("item_type", sa.String(length=20), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("task_id", sa.String(length=36), nullable=True),
            sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("risk", sa.String(length=10), nullable=True),
            sa.Column("complexity", sa.String(length=10), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.Column("blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("blocked_reason", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="roadmap_items_pkey"),
            sa.UniqueConstraint(
                "roadmap_id",
                "item_type",
                "project_id",
                "task_id",
                name="uq_roadmap_item",
                postgresql_nulls_not_distinct=True,
            ),
        )

    if "roadmaps" not in _existing_tables:
        op.create_table(
            "roadmaps",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
            ),
            sa.PrimaryKeyConstraint("id", name="roadmaps_pkey"),
            sa.UniqueConstraint("product_id", name="roadmaps_product_id_key"),
        )

    if "sequence_runs" not in _existing_tables:
        op.create_table(
            "sequence_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("project_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("resolved_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("current_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("execution_mode", sa.String(length=50), nullable=False),
            sa.Column(
                "status", sa.String(length=30), server_default=sa.text("'pending'::character varying"), nullable=False
            ),
            sa.Column(
                "review_policy",
                sa.String(length=30),
                server_default=sa.text("'per_card'::character varying"),
                nullable=False,
            ),
            sa.Column(
                "project_statuses",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("conductor_agent_id", sa.String(length=64), nullable=True),
            sa.Column("conductor_project_id", sa.String(length=36), nullable=True),
            sa.Column("conductor_label", sa.String(length=80), nullable=True),
            sa.Column("locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("chain_mission", sa.Text(), nullable=True),
            sa.Column(
                "reviewed_project_ids",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name="sequence_runs_pkey"),
        )

    if "server_runtime_metrics" not in _existing_tables:
        op.create_table(
            "server_runtime_metrics",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("worker_id", sa.String(length=128), nullable=False),
            sa.Column("metric", sa.String(length=64), nullable=False),
            sa.Column("value", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name="server_runtime_metrics_pkey"),
            sa.UniqueConstraint("worker_id", "metric", name="uq_server_runtime_metric_worker_metric"),
        )

    if "settings" not in _existing_tables:
        op.create_table(
            "settings",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("settings_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id", name="settings_pkey"),
            sa.UniqueConstraint("tenant_key", "category", name="uq_settings_tenant_category"),
        )

    if "setup_state" not in _existing_tables:
        op.create_table(
            "setup_state",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("database_initialized", sa.Boolean(), nullable=False),
            sa.Column("database_initialized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("setup_version", sa.String(length=20), nullable=True),
            sa.Column("python_version", sa.String(length=20), nullable=True),
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
                "validation_failures",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                comment="Array of validation failure messages",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "(((database_initialized = false) OR ((database_initialized = true) AND (database_initialized_at IS NOT NULL))))",
                name="ck_database_initialized_at_required",
            ),
            sa.CheckConstraint(
                "(((first_admin_created = false) OR ((first_admin_created = true) AND (first_admin_created_at IS NOT NULL))))",
                name="ck_first_admin_created_at_required",
            ),
            sa.CheckConstraint(
                "(((setup_version IS NULL) OR ((setup_version)::text ~ '^[0-9]+\\.[0-9]+\\.[0-9]+(-[a-zA-Z0-9\\.\\-]+)?$'::text)))",
                name="ck_setup_version_format",
            ),
            sa.PrimaryKeyConstraint("id", name="setup_state_pkey"),
        )

    if "system_settings" not in _existing_tables:
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.PrimaryKeyConstraint("key", name="system_settings_pkey"),
        )

    if "tasks" not in _existing_tables:
        op.create_table(
            "tasks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column(
                "org_id",
                sa.String(length=36),
                nullable=True,
                comment="Organization for org-level tasks (Handover 0424)",
            ),
            sa.Column("product_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("parent_task_id", sa.String(length=36), nullable=True),
            sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("converted_to_project_id", sa.String(length=36), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=True),
            sa.Column("priority", sa.String(length=20), nullable=True),
            sa.Column("estimated_effort", sa.Float(precision=53), nullable=True),
            sa.Column("actual_effort", sa.Float(precision=53), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("task_type_id", sa.String(length=36), nullable=True),
            sa.Column("series_number", sa.Integer(), nullable=True),
            sa.Column("subseries", sa.String(length=1), nullable=True),
            sa.Column(
                "hidden",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
                comment="Whether task is hidden from default list view (UI declutter only)",
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name="tasks_pkey"),
        )

    if "taxonomy_types" not in _existing_tables:
        op.create_table(
            "taxonomy_types",
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
            sa.PrimaryKeyConstraint("id", name="taxonomy_types_pkey"),
            sa.UniqueConstraint("tenant_key", "abbreviation", name="uq_taxonomy_type_abbr"),
        )

    if "template_archives" not in _existing_tables:
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
            sa.Column("avg_generation_ms_at_archive", sa.Float(precision=53), nullable=True),
            sa.Column("is_restorable", sa.Boolean(), nullable=True),
            sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("restored_by", sa.String(length=100), nullable=True),
            sa.PrimaryKeyConstraint("id", name="template_archives_pkey"),
        )

    if "tenant_skills_ack" not in _existing_tables:
        op.create_table(
            "tenant_skills_ack",
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("acknowledged_version", sa.String(length=128), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
            ),
            sa.PrimaryKeyConstraint("tenant_key", name="tenant_skills_ack_pkey"),
        )

    if "user_approvals" not in _existing_tables:
        op.create_table(
            "user_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=50), nullable=False),
            sa.Column("agent_execution_id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "status", sa.String(length=20), server_default=sa.text("'pending'::character varying"), nullable=False
            ),
            sa.Column("decided_option_id", sa.String(length=100), nullable=True),
            sa.Column("decided_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "decided_via",
                sa.String(length=10),
                nullable=True,
                comment="BE-9514: which door decided this ('ui' | 'mcp'); NULL for legacy rows predating the column",
            ),
            sa.CheckConstraint(
                "status IN ('pending', 'decided', 'expired', 'cancelled')", name="ck_user_approvals_status"
            ),
            sa.CheckConstraint(
                "decided_via IS NULL OR decided_via IN ('ui', 'mcp')", name="ck_user_approvals_decided_via"
            ),
            sa.PrimaryKeyConstraint("id", name="user_approvals_pkey"),
        )

    if "user_field_priorities" not in _existing_tables:
        op.create_table(
            "user_field_priorities",
            sa.Column("id", sa.String(length=36), server_default=sa.text("(gen_random_uuid())::text"), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name="user_field_priorities_pkey"),
            sa.UniqueConstraint("user_id", "category", name="uq_user_field_priorities_user_category"),
        )

    if "users" not in _existing_tables:
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
            sa.Column(
                "depth_vision_documents",
                sa.String(length=20),
                server_default=sa.text("'medium'::character varying"),
                nullable=False,
            ),
            sa.Column("depth_memory_last_n", sa.Integer(), server_default=sa.text("3"), nullable=False),
            sa.Column("depth_git_commits", sa.Integer(), server_default=sa.text("25"), nullable=False),
            sa.Column(
                "depth_agent_templates",
                sa.String(length=20),
                server_default=sa.text("'basic'::character varying"),
                nullable=False,
            ),
            sa.Column(
                "depth_tech_stack_sections",
                sa.String(length=20),
                server_default=sa.text("'all'::character varying"),
                nullable=False,
            ),
            sa.Column(
                "depth_architecture",
                sa.String(length=20),
                server_default=sa.text("'overview'::character varying"),
                nullable=False,
            ),
            sa.Column("setup_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("setup_selected_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("setup_step_completed", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("learning_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column(
                "password_nudge_dismissed_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="BE-1004: one-time 'set a password' nudge dismissal for social-only users",
            ),
            sa.Column("registration_ip", sa.String(length=45), nullable=True),
            sa.Column("token_revocation_epoch", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column(
                "learning_beat",
                sa.Integer(),
                nullable=True,
                comment="BE-9201: last onboarding-tutorial beat reached (1-6); NULL until the tutorial persists it",
            ),
            sa.Column(
                "router_choice",
                sa.String(length=8),
                nullable=True,
                comment="BE-9201: tutorial router door picked (A|B|C|D); drives the bootstrap-card spotlight",
            ),
            sa.CheckConstraint("((failed_pin_attempts >= 0))", name="ck_user_pin_attempts_positive"),
            sa.CheckConstraint("role IN ('admin', 'developer', 'viewer')", name="ck_user_role"),
            sa.PrimaryKeyConstraint("id", name="users_pkey"),
        )

    if "vision_documents" not in _existing_tables:
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
            sa.Column(
                "vision_document", sa.Text(), nullable=True, comment="Inline vision text (inline or hybrid storage)"
            ),
            sa.Column(
                "storage_type",
                sa.String(length=20),
                nullable=False,
                comment="Storage mode: 'file', 'inline', or 'hybrid'",
            ),
            sa.Column(
                "chunked",
                sa.Boolean(),
                nullable=False,
                comment="Has document been chunked into mcp_context_index for RAG",
            ),
            sa.Column(
                "chunk_count", sa.Integer(), nullable=False, comment="Number of chunks created for this document"
            ),
            sa.Column("total_tokens", sa.Integer(), nullable=True, comment="Estimated total tokens in document"),
            sa.Column(
                "file_size",
                sa.BigInteger(),
                nullable=True,
                comment="Original file size in bytes (NULL for inline content without file)",
            ),
            sa.Column(
                "is_summarized",
                sa.Boolean(),
                nullable=False,
                comment="True once the per-document agent summaries (summary_light + summary_medium) have been populated on this row via update_product_fields.",
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
            sa.Column(
                "summary_light_tokens", sa.Integer(), nullable=True, comment="Actual token count in light summary"
            ),
            sa.Column(
                "summary_medium_tokens", sa.Integer(), nullable=True, comment="Actual token count in medium summary"
            ),
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
            sa.Column(
                "display_order", sa.Integer(), nullable=False, comment="Display order in UI (lower numbers first)"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "meta_data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
                comment="Additional metadata: author, tags, source_url, etc.",
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("((chunk_count >= 0))", name="ck_vision_doc_chunk_count"),
            sa.CheckConstraint(
                "((((chunked = false) AND (chunk_count = 0)) OR ((chunked = true) AND (chunk_count > 0))))",
                name="ck_vision_doc_chunked_consistency",
            ),
            sa.CheckConstraint(
                "document_type IN ('vision', 'architecture', 'features', 'setup', 'api', 'testing', 'deployment', 'custom')",
                name="ck_vision_doc_document_type",
            ),
            sa.CheckConstraint(
                "((((storage_type)::text = 'inline'::text) AND (vision_document IS NOT NULL) AND (vision_path IS NULL)))",
                name="ck_vision_doc_inline_only",
            ),
            sa.CheckConstraint("(((storage_type)::text = 'inline'::text))", name="ck_vision_doc_storage_type"),
            sa.PrimaryKeyConstraint("id", name="vision_documents_pkey"),
        )

    for _idx_sql in _INDEXES:
        op.execute(_idx_sql)

    for _fk_sql in _FOREIGN_KEYS:
        op.execute(_fk_sql)


def downgrade() -> None:
    pass


_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_agent_executions_agent_id ON public.agent_executions USING btree (agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_executions_health ON public.agent_executions USING btree (health_status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_executions_job ON public.agent_executions USING btree (job_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_executions_last_progress ON public.agent_executions USING btree (last_progress_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_executions_status ON public.agent_executions USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_executions_tenant_job_started ON public.agent_executions USING btree (tenant_key, job_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_agent_jobs_project ON public.agent_jobs USING btree (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON public.agent_jobs USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_jobs_tenant_created ON public.agent_jobs USING btree (tenant_key, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_agent_jobs_tenant_project ON public.agent_jobs USING btree (tenant_key, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_templates_tenant_updated ON public.agent_templates USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_todo_items_tenant_updated ON public.agent_todo_items USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_api_metrics_tenant_date ON public.api_metrics USING btree (tenant_key, date)",
    "CREATE INDEX IF NOT EXISTS idx_apikey_active ON public.api_keys USING btree (is_active)",
    "CREATE INDEX IF NOT EXISTS idx_apikey_permissions_gin ON public.api_keys USING gin (permissions)",
    "CREATE INDEX IF NOT EXISTS idx_apikey_tenant ON public.api_keys USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_apikey_user ON public.api_keys USING btree (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_archive_date ON public.template_archives USING btree (archived_at)",
    "CREATE INDEX IF NOT EXISTS idx_archive_product ON public.template_archives USING btree (product_id)",
    "CREATE INDEX IF NOT EXISTS idx_archive_template ON public.template_archives USING btree (template_id)",
    "CREATE INDEX IF NOT EXISTS idx_archive_tenant ON public.template_archives USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_archive_version ON public.template_archives USING btree (version)",
    "CREATE INDEX IF NOT EXISTS idx_assignment_active ON public.product_agent_assignments USING btree (is_active)",
    "CREATE INDEX IF NOT EXISTS idx_assignment_template ON public.product_agent_assignments USING btree (template_id)",
    "CREATE INDEX IF NOT EXISTS idx_assignment_tenant ON public.product_agent_assignments USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_comm_participant_lookup ON public.comm_participants USING btree (tenant_key, participant_id)",
    "CREATE INDEX IF NOT EXISTS idx_comm_thread_owner ON public.comm_threads USING btree (tenant_key, next_action_owner)",
    "CREATE INDEX IF NOT EXISTS idx_comm_thread_product ON public.comm_threads USING btree (product_id)",
    "CREATE INDEX IF NOT EXISTS idx_comm_thread_project ON public.comm_threads USING btree (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_comm_thread_status ON public.comm_threads USING btree (tenant_key, status)",
    "CREATE INDEX IF NOT EXISTS idx_comm_threads_tenant_updated ON public.comm_threads USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_config_category ON public.configurations USING btree (category)",
    "CREATE INDEX IF NOT EXISTS idx_configurations_tenant_updated ON public.configurations USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_download_token_expires ON public.download_tokens USING btree (expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_download_token_tenant_type ON public.download_tokens USING btree (tenant_key, download_type)",
    "CREATE INDEX IF NOT EXISTS idx_login_lockout_locked_until ON public.login_lockouts USING btree (locked_until)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_context_product_vision_doc ON public.mcp_context_index USING btree (product_id, vision_document_id)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_context_tenant_product ON public.mcp_context_index USING btree (tenant_key, product_id)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_context_vision_doc ON public.mcp_context_index USING btree (vision_document_id)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_session_api_key ON public.mcp_sessions USING btree (api_key_id)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_session_cleanup ON public.mcp_sessions USING btree (expires_at, last_accessed)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_session_data_gin ON public.mcp_sessions USING gin (session_data)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_session_last_accessed ON public.mcp_sessions USING btree (last_accessed)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_session_tenant ON public.mcp_sessions USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_session_user ON public.mcp_sessions USING btree (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_membership_tenant ON public.org_memberships USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_membership_user ON public.org_memberships USING btree (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_message_acks_agent ON public.message_acknowledgments USING btree (agent_id, tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_message_acks_tenant ON public.message_acknowledgments USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_message_completions_agent ON public.message_completions USING btree (agent_id, tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_message_completions_tenant ON public.message_completions USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_message_created ON public.messages USING btree (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_message_priority ON public.messages USING btree (priority)",
    "CREATE INDEX IF NOT EXISTS idx_message_project ON public.messages USING btree (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_message_recipients_agent ON public.message_recipients USING btree (agent_id, tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_message_recipients_tenant ON public.message_recipients USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_message_status ON public.messages USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_messages_tenant_created ON public.messages USING btree (tenant_key, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_messages_tenant_from_agent_created ON public.messages USING btree (tenant_key, from_agent_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON public.messages USING btree (thread_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_dedupe_key ON public.notifications USING btree (dedupe_key)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_tenant_user_created ON public.notifications USING btree (tenant_key, user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_code_expires ON public.oauth_authorization_codes USING btree (expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_code_lookup ON public.oauth_authorization_codes USING btree (code, tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_code_tenant ON public.oauth_authorization_codes USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_code_user ON public.oauth_authorization_codes USING btree (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_org_active ON public.organizations USING btree (is_active)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_org_slug ON public.organizations USING btree (slug)",
    "CREATE INDEX IF NOT EXISTS idx_org_tenant ON public.organizations USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_organizations_tenant_updated ON public.organizations USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_pme_deleted ON public.product_memory_entries USING btree (deleted_by_user) WHERE (deleted_by_user = true)",
    "CREATE INDEX IF NOT EXISTS idx_pme_fts ON public.product_memory_entries USING gin (to_tsvector('english'::regconfig, ((((((((((COALESCE(summary, ''::text) || ' '::text) || (COALESCE(project_name, ''::character varying))::text) || ' '::text) || COALESCE((key_outcomes)::text, ''::text)) || ' '::text) || COALESCE((decisions_made)::text, ''::text)) || ' '::text) || COALESCE((tags)::text, ''::text)) || ' '::text) || COALESCE((git_commits)::text, ''::text))))",
    "CREATE INDEX IF NOT EXISTS idx_pme_project ON public.product_memory_entries USING btree (project_id) WHERE (project_id IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_pme_tenant_product ON public.product_memory_entries USING btree (tenant_key, product_id)",
    'CREATE INDEX IF NOT EXISTS idx_pme_tenant_timestamp ON public.product_memory_entries USING btree (tenant_key, "timestamp" DESC)',
    "CREATE INDEX IF NOT EXISTS idx_pme_type ON public.product_memory_entries USING btree (entry_type)",
    "CREATE INDEX IF NOT EXISTS idx_product_agent_assignments_tenant_updated ON public.product_agent_assignments USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_product_architectures_tenant ON public.product_architectures USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_product_architectures_tenant_updated ON public.product_architectures USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_product_memory_entries_tenant_updated ON public.product_memory_entries USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_product_memory_gin ON public.products USING gin (product_memory)",
    "CREATE INDEX IF NOT EXISTS idx_product_name ON public.products USING btree (name)",
    "CREATE INDEX IF NOT EXISTS idx_product_org_id ON public.products USING btree (org_id)",
    "CREATE INDEX IF NOT EXISTS idx_product_tech_stacks_tenant ON public.product_tech_stacks USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_product_tech_stacks_tenant_updated ON public.product_tech_stacks USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_product_tenant ON public.products USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_product_test_configs_tenant ON public.product_test_configs USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_product_test_configs_tenant_updated ON public.product_test_configs USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_products_consolidated_at ON public.products USING btree (consolidated_at)",
    "CREATE INDEX IF NOT EXISTS idx_products_deleted_at ON public.products USING btree (deleted_at) WHERE (deleted_at IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_products_tenant_updated ON public.products USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_project_status ON public.projects USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_project_tenant ON public.projects USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_projects_closeout_executed ON public.projects USING btree (closeout_executed_at) WHERE (closeout_executed_at IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_projects_deleted_at ON public.projects USING btree (deleted_at) WHERE (deleted_at IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_projects_tenant_created ON public.projects USING btree (tenant_key, created_at DESC) WHERE (deleted_at IS NULL)",
    "CREATE INDEX IF NOT EXISTS idx_projects_tenant_updated ON public.projects USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_roadmap_item_tenant ON public.roadmap_items USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_roadmap_items_tenant_updated ON public.roadmap_items USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_roadmap_tenant ON public.roadmaps USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_roadmaps_tenant_updated ON public.roadmaps USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_sequence_runs_tenant ON public.sequence_runs USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_sequence_runs_tenant_updated ON public.sequence_runs USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_settings_category ON public.settings USING btree (category)",
    "CREATE INDEX IF NOT EXISTS idx_settings_tenant_updated ON public.settings USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_setup_database_incomplete ON public.setup_state USING btree (tenant_key, database_initialized) WHERE (database_initialized = false)",
    "CREATE INDEX IF NOT EXISTS idx_setup_database_initialized ON public.setup_state USING btree (database_initialized)",
    "CREATE INDEX IF NOT EXISTS idx_setup_fresh_install ON public.setup_state USING btree (tenant_key, first_admin_created) WHERE (first_admin_created = false)",
    "CREATE INDEX IF NOT EXISTS idx_setup_state_tenant_updated ON public.setup_state USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_task_converted_to_project ON public.tasks USING btree (converted_to_project_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_created_by_user ON public.tasks USING btree (created_by_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_org_id ON public.tasks USING btree (org_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_priority ON public.tasks USING btree (priority)",
    "CREATE INDEX IF NOT EXISTS idx_task_product ON public.tasks USING btree (product_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_project ON public.tasks USING btree (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_status ON public.tasks USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_task_task_type_id ON public.tasks USING btree (task_type_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_tenant_created_user ON public.tasks USING btree (tenant_key, created_by_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_deleted_at ON public.tasks USING btree (deleted_at) WHERE (deleted_at IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_taxonomy_types_tenant_updated ON public.taxonomy_types USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_template_active ON public.agent_templates USING btree (is_active)",
    "CREATE INDEX IF NOT EXISTS idx_template_category ON public.agent_templates USING btree (category)",
    "CREATE INDEX IF NOT EXISTS idx_template_deleted_at ON public.agent_templates USING btree (deleted_at) WHERE (deleted_at IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_template_org_id ON public.agent_templates USING btree (org_id)",
    "CREATE INDEX IF NOT EXISTS idx_template_role ON public.agent_templates USING btree (role)",
    "CREATE INDEX IF NOT EXISTS idx_template_tenant ON public.agent_templates USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_template_tool ON public.agent_templates USING btree (tool)",
    "CREATE INDEX IF NOT EXISTS idx_tenant_skills_ack_tenant_updated ON public.tenant_skills_ack USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_todo_items_job_sequence ON public.agent_todo_items USING btree (job_id, sequence)",
    "CREATE INDEX IF NOT EXISTS idx_todo_items_tenant_status ON public.agent_todo_items USING btree (tenant_key, status)",
    "CREATE INDEX IF NOT EXISTS idx_user_active ON public.users USING btree (is_active)",
    "CREATE INDEX IF NOT EXISTS idx_user_field_priorities_tenant_updated ON public.user_field_priorities USING btree (tenant_key, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_user_field_priorities_user ON public.user_field_priorities USING btree (user_id, tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_user_org_id ON public.users USING btree (org_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_pin_lockout ON public.users USING btree (pin_lockout_until)",
    "CREATE INDEX IF NOT EXISTS idx_user_system ON public.users USING btree (is_system_user)",
    "CREATE INDEX IF NOT EXISTS idx_user_tenant ON public.users USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_active ON public.vision_documents USING btree (is_active)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_chunked ON public.vision_documents USING btree (chunked)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_deleted_at ON public.vision_documents USING btree (deleted_at) WHERE (deleted_at IS NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_product_active ON public.vision_documents USING btree (product_id, is_active, display_order)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_product_type ON public.vision_documents USING btree (product_id, document_type)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_tenant_product ON public.vision_documents USING btree (tenant_key, product_id)",
    "CREATE INDEX IF NOT EXISTS idx_vision_doc_type ON public.vision_documents USING btree (document_type)",
    "CREATE INDEX IF NOT EXISTS idx_vision_documents_tenant_updated ON public.vision_documents USING btree (tenant_key, updated_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_key_hash ON public.api_keys USING btree (key_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_api_metrics_tenant_key ON public.api_metrics USING btree (tenant_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_download_tokens_token ON public.download_tokens USING btree (token)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_mcp_sessions_session_id ON public.mcp_sessions USING btree (session_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_authorization_codes_code ON public.oauth_authorization_codes USING btree (code)",
    "CREATE INDEX IF NOT EXISTS ix_oauth_refresh_tokens_family_id ON public.oauth_refresh_tokens USING btree (family_id)",
    "CREATE INDEX IF NOT EXISTS ix_oauth_refresh_tokens_tenant_key ON public.oauth_refresh_tokens USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS ix_oauth_revoked_tokens_tenant_key ON public.oauth_revoked_tokens USING btree (tenant_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_alias ON public.projects USING btree (alias)",
    "CREATE INDEX IF NOT EXISTS ix_setup_state_first_admin_created ON public.setup_state USING btree (first_admin_created)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_setup_state_tenant_key ON public.setup_state USING btree (tenant_key)",
    "CREATE INDEX IF NOT EXISTS ix_user_approvals_agent_status ON public.user_approvals USING btree (agent_execution_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_user_approvals_tenant_status ON public.user_approvals USING btree (tenant_key, status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON public.users USING btree (email)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON public.users USING btree (username)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_tenant_dedupe_open ON public.notifications USING btree (tenant_key, dedupe_key) WHERE (resolved_at IS NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_taxonomy_active ON public.projects USING btree (tenant_key, product_id, project_type_id, series_number, subseries) NULLS NOT DISTINCT WHERE (deleted_at IS NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_taxonomy_active ON public.tasks USING btree (tenant_key, product_id, task_type_id, series_number, subseries) NULLS NOT DISTINCT WHERE ((series_number IS NOT NULL) AND (deleted_at IS NULL))",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_template_tenant_name_version ON public.agent_templates USING btree (tenant_key, name, version) WHERE (deleted_at IS NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_vision_doc_product_name ON public.vision_documents USING btree (product_id, document_name) WHERE (deleted_at IS NULL)",
]

_FOREIGN_KEYS = [
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_executions_job_id_fkey') THEN ALTER TABLE ONLY public.agent_executions ADD CONSTRAINT agent_executions_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.agent_jobs(job_id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_jobs_project_id_fkey') THEN ALTER TABLE ONLY public.agent_jobs ADD CONSTRAINT agent_jobs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_jobs_template_id_fkey') THEN ALTER TABLE ONLY public.agent_jobs ADD CONSTRAINT agent_jobs_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.agent_templates(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_templates_org_id_fkey') THEN ALTER TABLE ONLY public.agent_templates ADD CONSTRAINT agent_templates_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_todo_items_job_id_fkey') THEN ALTER TABLE ONLY public.agent_todo_items ADD CONSTRAINT agent_todo_items_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.agent_jobs(job_id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'api_key_ip_log_api_key_id_fkey') THEN ALTER TABLE ONLY public.api_key_ip_log ADD CONSTRAINT api_key_ip_log_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'api_keys_user_id_fkey') THEN ALTER TABLE ONLY public.api_keys ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'comm_participants_thread_id_fkey') THEN ALTER TABLE ONLY public.comm_participants ADD CONSTRAINT comm_participants_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.comm_threads(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'comm_threads_product_id_fkey') THEN ALTER TABLE ONLY public.comm_threads ADD CONSTRAINT comm_threads_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'comm_threads_project_id_fkey') THEN ALTER TABLE ONLY public.comm_threads ADD CONSTRAINT comm_threads_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'configurations_project_id_fkey') THEN ALTER TABLE ONLY public.configurations ADD CONSTRAINT configurations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mcp_context_index_product_id_fkey') THEN ALTER TABLE ONLY public.mcp_context_index ADD CONSTRAINT mcp_context_index_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mcp_context_index_vision_document_id_fkey') THEN ALTER TABLE ONLY public.mcp_context_index ADD CONSTRAINT mcp_context_index_vision_document_id_fkey FOREIGN KEY (vision_document_id) REFERENCES public.vision_documents(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_mcp_sessions_user_id') THEN ALTER TABLE ONLY public.mcp_sessions ADD CONSTRAINT fk_mcp_sessions_user_id FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mcp_sessions_api_key_id_fkey') THEN ALTER TABLE ONLY public.mcp_sessions ADD CONSTRAINT mcp_sessions_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mcp_sessions_project_id_fkey') THEN ALTER TABLE ONLY public.mcp_sessions ADD CONSTRAINT mcp_sessions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'message_acknowledgments_message_id_fkey') THEN ALTER TABLE ONLY public.message_acknowledgments ADD CONSTRAINT message_acknowledgments_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'message_completions_message_id_fkey') THEN ALTER TABLE ONLY public.message_completions ADD CONSTRAINT message_completions_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'message_recipients_message_id_fkey') THEN ALTER TABLE ONLY public.message_recipients ADD CONSTRAINT message_recipients_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'messages_project_id_fkey') THEN ALTER TABLE ONLY public.messages ADD CONSTRAINT messages_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'messages_thread_id_fkey') THEN ALTER TABLE ONLY public.messages ADD CONSTRAINT messages_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.comm_threads(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_user_id_fkey') THEN ALTER TABLE ONLY public.notifications ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'oauth_authorization_codes_user_id_fkey') THEN ALTER TABLE ONLY public.oauth_authorization_codes ADD CONSTRAINT oauth_authorization_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'oauth_refresh_tokens_user_id_fkey') THEN ALTER TABLE ONLY public.oauth_refresh_tokens ADD CONSTRAINT oauth_refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'org_memberships_invited_by_fkey') THEN ALTER TABLE ONLY public.org_memberships ADD CONSTRAINT org_memberships_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.users(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'org_memberships_org_id_fkey') THEN ALTER TABLE ONLY public.org_memberships ADD CONSTRAINT org_memberships_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'org_memberships_user_id_fkey') THEN ALTER TABLE ONLY public.org_memberships ADD CONSTRAINT org_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_agent_assignments_product_id_fkey') THEN ALTER TABLE ONLY public.product_agent_assignments ADD CONSTRAINT product_agent_assignments_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_agent_assignments_template_id_fkey') THEN ALTER TABLE ONLY public.product_agent_assignments ADD CONSTRAINT product_agent_assignments_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.agent_templates(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_architectures_product_id_fkey') THEN ALTER TABLE ONLY public.product_architectures ADD CONSTRAINT product_architectures_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_memory_entries_product_id_fkey') THEN ALTER TABLE ONLY public.product_memory_entries ADD CONSTRAINT product_memory_entries_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_memory_entries_project_id_fkey') THEN ALTER TABLE ONLY public.product_memory_entries ADD CONSTRAINT product_memory_entries_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_tech_stacks_product_id_fkey') THEN ALTER TABLE ONLY public.product_tech_stacks ADD CONSTRAINT product_tech_stacks_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'product_test_configs_product_id_fkey') THEN ALTER TABLE ONLY public.product_test_configs ADD CONSTRAINT product_test_configs_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_org_id_fkey') THEN ALTER TABLE ONLY public.products ADD CONSTRAINT products_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_product_id_fkey') THEN ALTER TABLE ONLY public.projects ADD CONSTRAINT projects_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_taxonomy_type_id_fkey') THEN ALTER TABLE ONLY public.projects ADD CONSTRAINT projects_taxonomy_type_id_fkey FOREIGN KEY (project_type_id) REFERENCES public.taxonomy_types(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roadmap_items_project_id_fkey') THEN ALTER TABLE ONLY public.roadmap_items ADD CONSTRAINT roadmap_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roadmap_items_roadmap_id_fkey') THEN ALTER TABLE ONLY public.roadmap_items ADD CONSTRAINT roadmap_items_roadmap_id_fkey FOREIGN KEY (roadmap_id) REFERENCES public.roadmaps(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roadmap_items_task_id_fkey') THEN ALTER TABLE ONLY public.roadmap_items ADD CONSTRAINT roadmap_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roadmaps_product_id_fkey') THEN ALTER TABLE ONLY public.roadmaps ADD CONSTRAINT roadmaps_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_converted_to_project_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_converted_to_project_id_fkey FOREIGN KEY (converted_to_project_id) REFERENCES public.projects(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_created_by_user_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_org_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_parent_task_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_parent_task_id_fkey FOREIGN KEY (parent_task_id) REFERENCES public.tasks(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_product_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_project_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_task_type_id_fkey') THEN ALTER TABLE ONLY public.tasks ADD CONSTRAINT tasks_task_type_id_fkey FOREIGN KEY (task_type_id) REFERENCES public.taxonomy_types(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'template_archives_template_id_fkey') THEN ALTER TABLE ONLY public.template_archives ADD CONSTRAINT template_archives_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.agent_templates(id); END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_approvals_agent_execution_id_fkey') THEN ALTER TABLE ONLY public.user_approvals ADD CONSTRAINT user_approvals_agent_execution_id_fkey FOREIGN KEY (agent_execution_id) REFERENCES public.agent_executions(id) ON DELETE RESTRICT; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_approvals_decided_by_user_id_fkey') THEN ALTER TABLE ONLY public.user_approvals ADD CONSTRAINT user_approvals_decided_by_user_id_fkey FOREIGN KEY (decided_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_approvals_job_id_fkey') THEN ALTER TABLE ONLY public.user_approvals ADD CONSTRAINT user_approvals_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.agent_jobs(job_id) ON DELETE RESTRICT; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_approvals_project_id_fkey') THEN ALTER TABLE ONLY public.user_approvals ADD CONSTRAINT user_approvals_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE RESTRICT; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_field_priorities_user_id_fkey') THEN ALTER TABLE ONLY public.user_field_priorities ADD CONSTRAINT user_field_priorities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_org_id_fkey') THEN ALTER TABLE ONLY public.users ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE SET NULL; END IF; END $$;",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'vision_documents_product_id_fkey') THEN ALTER TABLE ONLY public.vision_documents ADD CONSTRAINT vision_documents_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE CASCADE; END IF; END $$;",
]
