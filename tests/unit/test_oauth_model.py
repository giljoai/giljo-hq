# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime, timedelta

from giljo_mcp.models.base import generate_uuid
from giljo_mcp.models.oauth import OAuthAuthorizationCode


class TestGenerateUuid:

    def test_generate_uuid_returns_string(self):
        result = generate_uuid()
        assert isinstance(result, str)

    def test_generate_uuid_produces_unique_values(self):
        ids = {generate_uuid() for _ in range(100)}
        assert len(ids) == 100

    def test_generate_uuid_valid_format(self):
        result = generate_uuid()
        parts = result.split("-")
        assert len(parts) == 5
        assert len(result) == 36


class TestOAuthAuthorizationCodeModel:

    def test_tablename(self):
        assert OAuthAuthorizationCode.__tablename__ == "oauth_authorization_codes"

    def test_model_has_expected_columns(self):
        mapper = OAuthAuthorizationCode.__table__
        column_names = {col.name for col in mapper.columns}
        expected = {
            "id",
            "code",
            "client_id",
            "user_id",
            "tenant_key",
            "redirect_uri",
            "code_challenge",
            "code_challenge_method",
            "scope",
            "expires_at",
            "used",
            "created_at",
        }
        assert expected.issubset(column_names), f"Missing columns: {expected - column_names}"

    def test_code_column_is_unique_and_indexed(self):
        code_col = OAuthAuthorizationCode.__table__.c.code
        assert code_col.unique is True
        assert code_col.index is True

    def test_code_column_is_not_nullable(self):
        code_col = OAuthAuthorizationCode.__table__.c.code
        assert code_col.nullable is False

    def test_client_id_not_nullable(self):
        col = OAuthAuthorizationCode.__table__.c.client_id
        assert col.nullable is False

    def test_user_id_has_foreign_key(self):
        col = OAuthAuthorizationCode.__table__.c.user_id
        assert col.nullable is False
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "users.id" in fk_targets

    def test_tenant_key_not_nullable(self):
        col = OAuthAuthorizationCode.__table__.c.tenant_key
        assert col.nullable is False

    def test_redirect_uri_not_nullable(self):
        col = OAuthAuthorizationCode.__table__.c.redirect_uri
        assert col.nullable is False

    def test_code_challenge_not_nullable(self):
        col = OAuthAuthorizationCode.__table__.c.code_challenge
        assert col.nullable is False

    def test_code_challenge_method_default(self):
        col = OAuthAuthorizationCode.__table__.c.code_challenge_method
        assert col.default.arg == "S256"

    def test_scope_default(self):
        col = OAuthAuthorizationCode.__table__.c.scope
        assert col.default.arg == "mcp:read mcp:write"

    def test_used_default(self):
        col = OAuthAuthorizationCode.__table__.c.used
        assert col.default.arg is False

    def test_expires_at_not_nullable(self):
        col = OAuthAuthorizationCode.__table__.c.expires_at
        assert col.nullable is False

    def test_expires_at_has_timezone(self):
        col = OAuthAuthorizationCode.__table__.c.expires_at
        assert col.type.timezone is True

    def test_created_at_has_server_default(self):
        col = OAuthAuthorizationCode.__table__.c.created_at
        assert col.server_default is not None

    def test_instantiation_with_required_fields(self):
        expires = datetime.now(UTC) + timedelta(minutes=10)
        instance = OAuthAuthorizationCode(
            code="test_auth_code_abc123",
            client_id="giljo-mcp-default",
            user_id="user-123",
            tenant_key="tenant-abc",
            redirect_uri="http://localhost:3000/callback",
            code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            expires_at=expires,
        )
        assert instance.code == "test_auth_code_abc123"
        assert instance.client_id == "giljo-mcp-default"
        assert instance.user_id == "user-123"
        assert instance.tenant_key == "tenant-abc"
        assert instance.redirect_uri == "http://localhost:3000/callback"
        assert instance.code_challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        assert instance.expires_at == expires

    def test_repr(self):
        instance = OAuthAuthorizationCode(
            id="abc-123",
            code="code-xyz",
            client_id="giljo-mcp-default",
            tenant_key="tenant-abc",
        )
        result = repr(instance)
        assert "abc-123" in result
        assert "tenant-abc" in result

    def test_tenant_key_indexed(self):
        table = OAuthAuthorizationCode.__table__
        assert any(list(ix.columns)[:1] == [table.c.tenant_key] for ix in table.indexes), (
            "expected an index leading on tenant_key"
        )
