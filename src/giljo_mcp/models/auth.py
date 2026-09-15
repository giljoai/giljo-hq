# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)

    org_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        comment="Direct foreign key to organization (Handover 0424m - nullable for SET NULL)",
    )

    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)

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

    setup_complete = Column(Boolean, default=False, nullable=False, server_default="false")
    setup_selected_tools = Column(JSONB, nullable=True)
    setup_step_completed = Column(Integer, default=0, nullable=False, server_default="0")
    learning_complete = Column(Boolean, default=False, nullable=False, server_default="false")
    learning_beat = Column(Integer, nullable=True)
    router_choice = Column(String(8), nullable=True)

    password_nudge_dismissed_at = Column(DateTime(timezone=True), nullable=True)

    is_system_user = Column(Boolean, default=False, nullable=False)

    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or self.full_name or self.username

    role = Column(String(32), nullable=False, default="developer")

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    registration_ip = Column(
        String(45),
        nullable=True,
        comment="Client IP captured at registration (audit/abuse signal); nullable for legacy rows",
    )

    token_revocation_epoch = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Forced-logout epoch (SEC-6011); bumped to reject all prior-minted JWTs",
    )

    notification_preferences = Column(
        JSONB,
        nullable=True,
        default=None,
        comment="User notification preferences: tuning reminders, thresholds",
    )

    depth_vision_documents = Column(String(20), nullable=False, default="medium", server_default="medium")
    depth_memory_last_n = Column(Integer, nullable=False, default=3, server_default="3")
    depth_git_commits = Column(Integer, nullable=False, default=25, server_default="25")
    depth_agent_templates = Column(String(20), nullable=False, default="basic", server_default="basic")
    depth_tech_stack_sections = Column(String(20), nullable=False, default="all", server_default="all")
    depth_architecture = Column(String(20), nullable=False, default="overview", server_default="overview")

    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    field_priorities = relationship("UserFieldPriority", back_populates="user", cascade="all, delete-orphan")

    organization = relationship("Organization", back_populates="users", foreign_keys="User.org_id")

    created_tasks = relationship("Task", foreign_keys="Task.created_by_user_id", back_populates="created_by_user")

    __table_args__ = (
        Index("idx_user_tenant", "tenant_key"),
        Index("idx_user_active", "is_active"),
        Index("idx_user_system", "is_system_user"),
        Index("idx_user_pin_lockout", "pin_lockout_until"),
        Index("idx_user_org_id", "org_id"),
        CheckConstraint("role IN ('admin', 'developer', 'viewer')", name="ck_user_role"),
        CheckConstraint("failed_pin_attempts >= 0", name="ck_user_pin_attempts_positive"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class UserFieldPriority(Base):

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
        UniqueConstraint("user_id", "category", name="uq_user_field_priorities_user_category"),
        Index("idx_user_field_priorities_user", "user_id", "tenant_key"),
        Index("idx_user_field_priorities_tenant_updated", "tenant_key", "updated_at"),
        CheckConstraint(
            f"category IN ({', '.join(repr(c) for c in sorted(TOGGLEABLE_CATEGORIES))})",
            name="ck_user_field_priority_category",
        ),
    )

    def __repr__(self) -> str:
        return f"<UserFieldPriority(user_id={self.user_id}, category={self.category}, enabled={self.enabled})>"


class APIKey(Base):

    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_key = Column(String(36), nullable=False)

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    key_prefix = Column(String(16), nullable=False)

    permissions = Column(JSONB, nullable=False, default=list)

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="api_keys")

    __table_args__ = (
        Index("idx_apikey_tenant", "tenant_key"),
        Index("idx_apikey_user", "user_id"),
        Index("idx_apikey_active", "is_active"),
        Index("idx_apikey_permissions_gin", "permissions", postgresql_using="gin"),
        CheckConstraint(
            "(is_active = true AND revoked_at IS NULL) OR (is_active = false)", name="ck_apikey_revoked_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name}, user_id={self.user_id}, active={self.is_active})>"


class ApiKeyIpLog(Base):

    __tablename__ = "api_key_ip_log"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False)
    ip_address = Column(String(45), nullable=False)
    request_count = Column(Integer, nullable=False, default=1)

    api_key = relationship("APIKey", backref="ip_logs")

    __table_args__ = (
        UniqueConstraint("api_key_id", "ip_address", name="uq_api_key_ip"),
    )

    def __repr__(self) -> str:
        return f"<ApiKeyIpLog(api_key_id={self.api_key_id}, ip={self.ip_address}, count={self.request_count})>"


class MCPSession(Base):

    __tablename__ = "mcp_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), unique=True, nullable=False, default=generate_uuid, index=True)

    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=True)
    tenant_key = Column(String(36), nullable=False)

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    session_data = Column(
        JSONB, nullable=False, default=dict, comment="MCP protocol state: client_info, capabilities, tool_call_history"
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    api_key = relationship("APIKey", backref="mcp_sessions")
    project = relationship("Project", backref="mcp_sessions")
    user = relationship("User", backref="mcp_sessions")

    __table_args__ = (
        Index("idx_mcp_session_api_key", "api_key_id"),
        Index("idx_mcp_session_tenant", "tenant_key"),
        Index("idx_mcp_session_user", "user_id"),
        Index("idx_mcp_session_last_accessed", "last_accessed"),
        Index("idx_mcp_session_cleanup", "expires_at", "last_accessed"),
        Index("idx_mcp_session_data_gin", "session_data", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<MCPSession(id={self.id}, session_id={self.session_id}, tenant_key={self.tenant_key})>"

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(UTC) > self.expires_at

    def extend_expiration(self, hours: int = 24) -> None:
        self.expires_at = datetime.now(UTC) + timedelta(hours=hours)
        self.last_accessed = datetime.now(UTC)


class LoginLockout(Base):

    __tablename__ = "login_lockouts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    identifier = Column(String(255), nullable=False, comment="Submitted username/email, lowercased")
    ip_address = Column(String(45), nullable=False, comment="Resolved client IP (IPv6 max length 45)")
    failed_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(
        DateTime(timezone=True), nullable=True, comment="Lockout expiry (UTC); NULL = not currently locked"
    )
    first_failed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("identifier", "ip_address", name="uq_login_lockout_identifier_ip"),
        Index("idx_login_lockout_locked_until", "locked_until"),
    )

    def __repr__(self) -> str:
        return f"<LoginLockout(identifier={self.identifier!r}, ip={self.ip_address!r}, failed={self.failed_count})>"
