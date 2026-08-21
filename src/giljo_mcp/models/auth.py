# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Authentication and authorization models.

This module contains all user authentication and session management models:
- User: User accounts for authentication
- APIKey: Personal API keys for MCP tool authentication
- ApiKeyIpLog: IP address tracking for API key usage auditing
- MCPSession: MCP HTTP session tracking with tenant isolation
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base, generate_uuid


# Valid categories for user_field_priorities (no product_info — always on)
TOGGLEABLE_CATEGORIES = frozenset(
    {
        "tech_stack",
        "architecture",
        "testing",
        "vision_documents",
        "memory_360",
        "git_history",
        "agent_templates",
    }
)


class User(Base):
    """
    User model - user accounts for authentication (LAN/WAN modes).

    Users are the primary authentication entity in LAN/WAN deployment modes.
    Each user can have multiple API keys for different applications/contexts.

    Phase 4 Enhancement: Task ownership and assignment tracking
    - created_tasks: Tasks created by this user
    - assigned_tasks: Tasks assigned to this user for completion

    Handover 0023: Password Reset and Recovery PIN
    - recovery_pin_hash: Hashed 4-digit recovery PIN for password reset
    - failed_pin_attempts: Track failed PIN attempts for rate limiting
    - pin_lockout_until: Timestamp when PIN lockout expires
    - must_change_password: Force password change on next login
    - must_set_pin: Force recovery PIN setup on next login

    Multi-tenant isolation: Users belong to a tenant_key namespace.

    Handover 0424f: User.org_id schema
    - org_id: Direct foreign key to organizations table (nullable for migration)
    - organization: Direct relationship to Organization model
    """

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: index served by explicit Index("idx_user_tenant") below; no
    # column-level index=True (that duplicated it as ix_users_tenant_key).
    tenant_key = Column(String(36), nullable=False)

    # Organization relationship (Handover 0424f, 0424m - nullable for SET NULL)
    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,  # FIXED: Must be True for ondelete="SET NULL" to work (0424m)
        # BE-8000c: indexed via explicit Index("idx_user_org_id") below.
        comment="Direct foreign key to organization (Handover 0424m - nullable for SET NULL)",
    )

    # Credentials. username/email keep unique=True+index=True (the UNIQUE
    # ix_users_username / ix_users_email indexes); the redundant plain
    # idx_user_username / idx_user_email were dropped (BE-8000c).
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for system users (auto-login only)

    # Recovery PIN for password reset (Handover 0023)
    recovery_pin_hash = Column(
        String(255), nullable=True, comment="Bcrypt hash of 4-digit recovery PIN for password reset"
    )
    failed_pin_attempts = Column(
        Integer, default=0, nullable=False, comment="Number of failed PIN verification attempts (rate limiting)"
    )
    pin_lockout_until = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when PIN lockout expires (15 minutes after 5 failed attempts)",
    )
    must_change_password = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Force user to change password on next login (new users, admin reset)",
    )
    must_set_pin = Column(
        Boolean, default=False, nullable=False, comment="Force user to set recovery PIN on next login (new users)"
    )

    # Setup wizard state (Handover 0855a)
    setup_complete = Column(Boolean, default=False, nullable=False, server_default="false")
    setup_selected_tools = Column(JSONB, nullable=True)
    setup_step_completed = Column(Integer, default=0, nullable=False, server_default="0")
    learning_complete = Column(Boolean, default=False, nullable=False, server_default="false")
    # BE-9201: onboarding-tutorial re-entry state. learning_beat = last beat the
    # user reached (1-6, validated at the PATCH boundary); router_choice = which
    # router door they picked ('A'|'B'|'C'|'D', drives the bootstrap-card
    # spotlight after reload). Both NULL until the tutorial persists them.
    learning_beat = Column(Integer, nullable=True)
    router_choice = Column(String(8), nullable=True)

    # BE-1004: one-time "set a password" nudge for first-time social-only users
    # (password_hash IS NULL). NULL = not dismissed yet; a light, skippable
    # signal only -- the email password-reset flow is the real recovery path.
    password_nudge_dismissed_at = Column(DateTime(timezone=True), nullable=True)

    # System user flag (for auto-login localhost user)
    is_system_user = Column(Boolean, default=False, nullable=False)

    # Profile
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    # full_name retained for one release as a transition shim. New writes
    # populate first_name/last_name and continue dual-writing full_name so
    # existing readers keep working; a follow-up migration will drop it.
    full_name = Column(String(255), nullable=True)

    @property
    def display_name(self) -> str:
        """Preferred display name: first/last when available, else legacy full_name, else username."""
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or self.full_name or self.username

    # Authorization
    role = Column(String(32), nullable=False, default="developer")
    # Roles: "admin", "developer", "viewer"

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    # Registration audit (BE-6109): client IP captured at account creation.
    # Nullable — existing rows predate the column and tolerate absence (no
    # backfill); abuse/fraud signal + audit trail, read by the SaaS Ops Panel.
    # Length 45 = IPv6 max (mirrors ApiKeyIpLog.ip_address).
    registration_ip = Column(
        String(45),
        nullable=True,
        comment="Client IP captured at registration (audit/abuse signal); nullable for legacy rows",
    )

    # Forced-logout revocation epoch (SEC-6011). Monotonic per-user counter that
    # an admin force-logout (or deactivation) bumps. The value at mint time is
    # embedded in each access JWT as the `rev` claim; validation rejects any
    # token whose `rev` is below the user's current epoch, so a single bump
    # invalidates ALL of that user's outstanding access tokens at once.
    # server_default 0 so existing rows + fresh inserts self-heal to a valid
    # baseline; numeric comparison treats absence as epoch 0.
    token_revocation_epoch = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Forced-logout epoch (SEC-6011); bumped to reject all prior-minted JWTs",
    )

    # Notification Preferences (Handover 0831)
    notification_preferences = Column(
        JSONB,
        nullable=True,
        default=None,
        comment="User notification preferences: tuning reminders, thresholds",
    )

    # Depth columns (Handover 0840d — replaces depth_config JSONB)
    depth_vision_documents = Column(String(20), nullable=False, default="medium", server_default="medium")
    depth_memory_last_n = Column(Integer, nullable=False, default=3, server_default="3")
    depth_git_commits = Column(Integer, nullable=False, default=25, server_default="25")
    depth_agent_templates = Column(String(20), nullable=False, default="basic", server_default="basic")
    depth_tech_stack_sections = Column(String(20), nullable=False, default="all", server_default="all")
    depth_architecture = Column(String(20), nullable=False, default="overview", server_default="overview")

    # Relationships
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    field_priorities = relationship("UserFieldPriority", back_populates="user", cascade="all, delete-orphan")

    # Organization relationship (Handover 0424f)
    organization = relationship("Organization", back_populates="users", foreign_keys="User.org_id")

    # Phase 4: Task relationships (Handover 0076: removed assigned_tasks)
    created_tasks = relationship("Task", foreign_keys="Task.created_by_user_id", back_populates="created_by_user")

    __table_args__ = (
        Index("idx_user_tenant", "tenant_key"),
        # BE-8000c: idx_user_username / idx_user_email dropped — the UNIQUE
        # ix_users_username / ix_users_email (from unique=True) already cover them.
        Index("idx_user_active", "is_active"),
        Index("idx_user_system", "is_system_user"),  # Index for system user queries
        Index("idx_user_pin_lockout", "pin_lockout_until"),  # Index for lockout queries (Handover 0023)
        Index("idx_user_org_id", "org_id"),  # Index for organization queries (Handover 0424f)
        CheckConstraint("role IN ('admin', 'developer', 'viewer')", name="ck_user_role"),
        CheckConstraint("failed_pin_attempts >= 0", name="ck_user_pin_attempts_positive"),  # Handover 0023
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class UserFieldPriority(Base):
    """
    User field priority toggle — one row per toggleable category per user.

    Handover 0840d: Replaces User.field_priority_config JSONB.
    Categories not present in this table are treated as enabled by default.
    product_info and project_description are always on (no rows stored).
    """

    __tablename__ = "user_field_priorities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_key = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="field_priorities")

    __table_args__ = (
        # BE-8000c: name aligned to the DB/baseline constraint name (was
        # "uq_user_field_priority" in the model → phantom drift add/remove).
        UniqueConstraint("user_id", "category", name="uq_user_field_priorities_user_category"),
        Index("idx_user_field_priorities_user", "user_id", "tenant_key"),
        # TSK-9076: backup watermark sweep — MAX(updated_at) per tenant.
        Index("idx_user_field_priorities_tenant_updated", "tenant_key", "updated_at"),
        CheckConstraint(
            f"category IN ({', '.join(repr(c) for c in sorted(TOGGLEABLE_CATEGORIES))})",
            name="ck_user_field_priority_category",
        ),
    )

    def __repr__(self) -> str:
        return f"<UserFieldPriority(user_id={self.user_id}, category={self.category}, enabled={self.enabled})>"


class APIKey(Base):
    """
    API Key model - personal API keys for MCP tool authentication.

    API keys enable programmatic access to the MCP server in LAN/WAN modes.
    Each key is scoped to a user and can have specific permissions.

    Security:
    - Keys are hashed using bcrypt before storage (never stored in plaintext)
    - key_prefix stores first 12 chars for display purposes only
    - Actual key is only returned once at creation time

    Multi-tenant isolation: API keys inherit tenant_key from their user.
    """

    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # BE-8000c: indexed via explicit Index("idx_apikey_tenant") below (no
    # column-level index=True — that duplicated it as ix_api_keys_tenant_key).
    tenant_key = Column(String(36), nullable=False)

    # Foreign key to user
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Key details
    name = Column(String(255), nullable=False)  # Description/label
    key_hash = Column(String(255), nullable=False, unique=True, index=True)  # Hashed API key (bcrypt)
    key_prefix = Column(String(16), nullable=False)  # First 12 chars for display (e.g., "gk_abc12...")

    # Permissions (JSON array)
    permissions = Column(JSONB, nullable=False, default=list)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="api_keys")

    __table_args__ = (
        Index("idx_apikey_tenant", "tenant_key"),
        Index("idx_apikey_user", "user_id"),
        # BE-8000c: idx_apikey_hash dropped — the UNIQUE ix_api_keys_key_hash
        # (from key_hash unique=True) already covers it.
        Index("idx_apikey_active", "is_active"),
        # GIN index for JSONB permissions (enables efficient permission queries)
        Index("idx_apikey_permissions_gin", "permissions", postgresql_using="gin"),
        # Ensure revoked_at is set when is_active=false
        CheckConstraint(
            "(is_active = true AND revoked_at IS NULL) OR (is_active = false)", name="ck_apikey_revoked_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name}, user_id={self.user_id}, active={self.is_active})>"


class ApiKeyIpLog(Base):
    """
    Tracks IP addresses used with each API key.

    Passive logging only - no enforcement. Used for security auditing
    and detecting potential key sharing/abuse.

    Upsert pattern: INSERT ON CONFLICT (api_key_id, ip_address)
    DO UPDATE SET request_count = request_count + 1
    """

    __tablename__ = "api_key_ip_log"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    ip_address = Column(String(45), nullable=False)
    request_count = Column(Integer, nullable=False, default=1)

    # Relationships
    api_key = relationship("APIKey", backref="ip_logs")

    __table_args__ = (
        # BE-8000c: idx_api_key_ip_log_key_id dropped — leftmost-covered by
        # uq_api_key_ip (api_key_id, ip_address).
        UniqueConstraint("api_key_id", "ip_address", name="uq_api_key_ip"),
    )

    def __repr__(self) -> str:
        return f"<ApiKeyIpLog(api_key_id={self.api_key_id}, ip={self.ip_address}, count={self.request_count})>"


class MCPSession(Base):
    """
    MCP Session model - tracks HTTP MCP sessions for stateful context preservation.

    Handover 0032: Enables pure MCP JSON-RPC 2.0 over HTTP with multi-tenant isolation.
    Sessions preserve tenant_key and project_id context across tool calls.

    Multi-tenant isolation: Sessions inherit tenant_key from API key's user.
    Session cleanup: Inactive sessions auto-expire after 24 hours.
    """

    __tablename__ = "mcp_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), unique=True, nullable=False, default=generate_uuid, index=True)

    # Foreign keys (nullable for OAuth JWT sessions that have no API key)
    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=True)
    # BE-8000c: indexed via explicit Index("idx_mcp_session_tenant") below.
    tenant_key = Column(String(36), nullable=False)

    # SECURITY: User ID for audit trail (Handover 0424 Phase 0)
    # BE-8000c: indexed via explicit Index("idx_mcp_session_user") below.
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    # Context preservation
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Session data (JSONB for performance)
    session_data = Column(
        JSONB, nullable=False, default=dict, comment="MCP protocol state: client_info, capabilities, tool_call_history"
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    api_key = relationship("APIKey", backref="mcp_sessions")
    project = relationship("Project", backref="mcp_sessions")
    user = relationship("User", backref="mcp_sessions")  # Handover 0424: Audit trail

    __table_args__ = (
        Index("idx_mcp_session_api_key", "api_key_id"),
        Index("idx_mcp_session_tenant", "tenant_key"),
        Index("idx_mcp_session_user", "user_id"),  # Handover 0424: Audit queries
        Index("idx_mcp_session_last_accessed", "last_accessed"),
        # BE-8000c: idx_mcp_session_expires dropped — leftmost-covered by
        # idx_mcp_session_cleanup (expires_at, last_accessed).
        # Composite index for session cleanup queries
        Index("idx_mcp_session_cleanup", "expires_at", "last_accessed"),
        # GIN index for session_data (enables efficient JSON queries)
        Index("idx_mcp_session_data_gin", "session_data", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<MCPSession(id={self.id}, session_id={self.session_id}, tenant_key={self.tenant_key})>"

    @property
    def is_expired(self) -> bool:
        """Check if session has expired"""
        if not self.expires_at:
            return False
        return datetime.now(UTC) > self.expires_at

    def extend_expiration(self, hours: int = 24) -> None:
        """Extend session expiration by specified hours"""
        self.expires_at = datetime.now(UTC) + timedelta(hours=hours)
        self.last_accessed = datetime.now(UTC)


class LoginLockout(Base):
    """Per-(identifier, IP) password-login lockout (SEC-3001a Wave 2 item 6).

    Pre-auth, system-level — NO ``tenant_key``. A failed login happens before
    any tenant context exists (exactly like the per-IP login rate limiter), so
    this table is intentionally outside the tenant axis and is NOT registered in
    ``_CE_TENANT_SCOPED_MODELS`` — the tenant guard skips it (SystemSetting /
    ServerRuntimeMetric precedent).

    Keying on ``(identifier, ip_address)`` rather than on the ``users`` row is
    deliberate and load-bearing (by design): an attacker spamming a
    victim's email from a DIFFERENT IP can only lock the ``(victim_email,
    attacker_ip)`` pair, never the victim's own ``(victim_email, victim_ip)`` —
    so the lockout itself can't be weaponised into an account-DoS. It also lets
    us count attempts against a non-existent identifier without leaking account
    existence (the row is keyed by what was typed, not by a real user id).
    """

    __tablename__ = "login_lockouts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # The login identifier exactly as submitted, lowercased for stable keying
    # (login accepts username OR email; we key on the raw typed value).
    identifier = Column(String(255), nullable=False, comment="Submitted username/email, lowercased")
    ip_address = Column(String(45), nullable=False, comment="Resolved client IP (IPv6 max length 45)")
    failed_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(
        DateTime(timezone=True), nullable=True, comment="Lockout expiry (UTC); NULL = not currently locked"
    )
    first_failed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        # BE-8000c: idx_login_lockout_identifier dropped — the instant-unlock
        # DELETE WHERE identifier=? is leftmost-covered by this unique index.
        UniqueConstraint("identifier", "ip_address", name="uq_login_lockout_identifier_ip"),
        # Expiry index: lets a future janitor prune rows whose window has passed.
        Index("idx_login_lockout_locked_until", "locked_until"),
    )

    def __repr__(self) -> str:
        return f"<LoginLockout(identifier={self.identifier!r}, ip={self.ip_address!r}, failed={self.failed_count})>"
