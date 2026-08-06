# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
OAuth 2.1 authorization models.

This module contains models for OAuth 2.1 Authorization Code flow with PKCE:
- OAuthAuthorizationCode: Short-lived authorization codes exchanged for tokens
- OAuthRefreshToken: Long-lived refresh tokens with family rotation +
  reuse detection (API-0021e Phase 2)
- OAuthRevokedToken: RFC 7009 revocation ledger keyed by JWT jti (API-0022)
"""

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
    """
    OAuth 2.1 Authorization Code with PKCE support.

    Stores short-lived authorization codes issued during the OAuth authorization
    flow. Codes are single-use, expire after 10 minutes, and require PKCE S256
    challenge verification at the token exchange step.

    Multi-tenant isolation: Every query MUST filter by tenant_key.
    """

    __tablename__ = "oauth_authorization_codes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(128), unique=True, nullable=False, index=True)
    client_id = Column(String(64), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # BE-8000c: indexed via explicit Index("idx_oauth_code_tenant") below (no
    # column-level index=True — that added a duplicate ix_* twin).
    tenant_key = Column(String(64), nullable=False)
    redirect_uri = Column(String(2048), nullable=False)
    code_challenge = Column(String(128), nullable=False)
    code_challenge_method = Column(String(10), default="S256")
    scope = Column(String(512), default="mcp:read mcp:write")
    # RFC 8707 resource indicator asserted at /authorize, validated at /token,
    # baked into the JWT `aud`. Nullable for backwards-compat with codes minted
    # before API-0021d (one-release transition window).
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
    """OAuth 2.1 refresh token with rotation + family reuse detection (API-0021e Phase 2).

    Refresh tokens are issued alongside the access token at /token (and
    rotated on every /refresh call). Each token is bound to a ``family_id``
    that groups every token derived from the same initial authorization-code
    grant. When a previously-rotated/revoked token is presented, the entire
    family is revoked and the security event is logged (RFC 6749 §10.4 +
    OAuth 2.1 Security BCP).

    Security contract:
      - The raw refresh token is NEVER persisted; only ``token_hash`` (sha256
        hex) is stored. Lookups go ``hash(presented) -> WHERE token_hash =``.
      - ``tenant_key`` is NOT NULL + indexed and is derived server-side from
        the resolved client at /refresh — never from the request body.
      - ``revoked`` is a one-way flip. To rotate, we mark the prior row
        ``revoked=true`` and insert a fresh row with the same ``family_id``.

    See ``OAuthService.refresh_token_grant`` for the runtime contract.
    """

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
    # SEC-9227b (M4): sha256 hex of the authorization code that minted this
    # family. Set only at initial /token issuance; NULL for rotated rows (the
    # family is revoked by family_id, not by this column) and for pre-migration
    # grants. Enables code-reuse detection to revoke every family born of a
    # replayed auth code (RFC 9700 §4.5.3). NEVER stores the raw code.
    origin_code_hash = Column(String(64), nullable=True)

    # Explicit __table_args__ indices match the migration (ce_0020). We don't
    # use ``index=True`` on the columns because that would create a second
    # index with the same auto-generated name, breaking ``create_all`` in tests.
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
    """RFC 7009 revocation ledger keyed by JWT ``jti`` (API-0022).

    The /mcp Bearer middleware looks up the presented JWT's ``jti`` claim
    against this table on every request (with a short-lived in-process TTL
    cache in front to keep the hot path cheap). A row here means the token
    has been revoked and must be treated as if it never existed.

    Security contract:
      - ``jti`` is the unique lookup key. JWTs minted before API-0022 may
        not carry a jti; rows for them simply do not exist and revocation
        is best-effort (those tokens roll off naturally as they expire).
      - ``tenant_key`` is NOT NULL + indexed; revocation is tenant-scoped
        (CLAUDE.md tenant-isolation rule).
      - ``token_type`` records the revoked type (``access_token`` or
        ``refresh_token``) per RFC 7009 token_type_hint. Refresh-token
        revocations additionally flip ``revoked=true`` on the entire
        ``oauth_refresh_tokens`` family (API-0021e §10.4 guidance).
      - This is an append-only ledger; rows are never deleted. A future
        background sweep may prune rows whose underlying JWT exp has
        passed, but the table is not load-bearing at JWT-issue time.
    """

    __tablename__ = "oauth_revoked_tokens"

    jti = Column(String(64), primary_key=True)
    token_type = Column(String(32), nullable=False)
    tenant_key = Column(String(64), nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_oauth_revoked_tokens_tenant_key", "tenant_key"),)

    def __repr__(self) -> str:
        return f"<OAuthRevokedToken(jti={self.jti}, token_type={self.token_type}, tenant_key={self.tenant_key})>"


__all__ = ["OAuthAuthorizationCode", "OAuthRefreshToken", "OAuthRevokedToken"]
