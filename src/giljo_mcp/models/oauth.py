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
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from .base import Base, generate_uuid


class OAuthAuthorizationCode(Base):

    __tablename__ = "oauth_authorization_codes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(128), unique=True, nullable=False, index=True)
    client_id = Column(String(64), nullable=False)
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
    client_id = Column(String(64), nullable=False)
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


__all__ = ["OAuthAuthorizationCode", "OAuthRefreshToken", "OAuthRevokedToken"]
