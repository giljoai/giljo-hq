# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class OAuthAuthorizationCode(Base):

    __tablename__ = "oauth_authorization_codes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(128), unique=True, nullable=False, index=True)
    client_id = Column(String(256), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_key = Column(String(64), nullable=False)
    redirect_uri = Column(String(2048), nullable=False)
    code_challenge = Column(String(128), nullable=False)
    code_challenge_method = Column(String(10), default="S256")
    scope = Column(String(512), default="mcp:read mcp:write")
    resource = Column(String(2048), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_oauth_code_tenant", "tenant_key"),
        Index("idx_oauth_code_user", "user_id"),
        Index("idx_oauth_code_expires", "expires_at"),
        Index("idx_oauth_code_lookup", "code", "tenant_key"),
    )

    def __repr__(self) -> str:
        return f"<OAuthAuthorizationCode(id={self.id}, client_id={self.client_id}, tenant_key={self.tenant_key})>"


class OAuthRefreshToken(Base):

    __tablename__ = "oauth_refresh_tokens"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    family_id = Column(PG_UUID(as_uuid=False), nullable=False)
    client_id = Column(String(256), nullable=False)
    tenant_key = Column(String(64), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope = Column(Text, nullable=True)
    aud = Column(Text, nullable=False)
    issued_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)
    origin_code_hash = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_oauth_refresh_tokens_family_id", "family_id"),
        Index("ix_oauth_refresh_tokens_tenant_key", "tenant_key"),
    )

    def __repr__(self) -> str:
        return (
            "<OAuthRefreshToken("
            f"id={self.id}, family_id={self.family_id}, "
            f"client_id={self.client_id}, tenant_key={self.tenant_key}, "
            f"revoked={self.revoked})>"
        )


class OAuthRevokedToken(Base):

    __tablename__ = "oauth_revoked_tokens"

    jti = Column(String(64), primary_key=True)
    token_type = Column(String(32), nullable=False)
    tenant_key = Column(String(64), nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_oauth_revoked_tokens_tenant_key", "tenant_key"),)

    def __repr__(self) -> str:
        return f"<OAuthRevokedToken(jti={self.jti}, token_type={self.token_type}, tenant_key={self.tenant_key})>"


class OAuthLogin(Base):

    __tablename__ = "oauth_logins"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    family_id = Column(PG_UUID(as_uuid=False), nullable=False, unique=True)
    tenant_key = Column(String(64), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(String(256), nullable=False)
    client_name = Column(String(200), nullable=False)
    connected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_ip = Column(String(45), nullable=True)
    last_user_agent = Column(String(256), nullable=True)
    last_mcp_client_name = Column(String(128), nullable=True)
    last_mcp_client_version = Column(String(64), nullable=True)
    last_product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("ix_oauth_logins_tenant_user", "tenant_key", "user_id"),)

    def __repr__(self) -> str:
        return f"<OAuthLogin(id={self.id}, family_id={self.family_id}, client_name={self.client_name})>"


class OAuthLoginIp(Base):

    __tablename__ = "oauth_login_ips"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    login_id = Column(String(36), ForeignKey("oauth_logins.id", ondelete="CASCADE"), nullable=False)
    tenant_key = Column(String(64), nullable=False)
    ip_address = Column(String(45), nullable=False)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    request_count = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("login_id", "ip_address", name="uq_oauth_login_ip"),
        Index("ix_oauth_login_ips_tenant_key", "tenant_key"),
    )

    def __repr__(self) -> str:
        return f"<OAuthLoginIp(login_id={self.login_id}, ip={self.ip_address}, count={self.request_count})>"


__all__ = ["OAuthAuthorizationCode", "OAuthLogin", "OAuthLoginIp", "OAuthRefreshToken", "OAuthRevokedToken"]
