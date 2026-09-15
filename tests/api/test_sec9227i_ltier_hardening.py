# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.endpoints.oauth import AuthorizeRequest, _enforce_oauth_field_caps
from giljo_mcp.services.oauth_service import OAuthService


FORBIDDEN_NON_C0 = ["\x80", "\x85", "\x9f", chr(0x2028), chr(0x2029)]


class TestAuthorizeFieldValidator:
    @pytest.mark.parametrize("bad", FORBIDDEN_NON_C0)
    def test_rejects_c1_controls_and_line_separators(self, bad):
        with pytest.raises(ValidationError):
            AuthorizeRequest(
                client_id="ok",
                redirect_uri="https://ok.example/cb",
                code_challenge=f"chal{bad}lenge",
            )

    @pytest.mark.parametrize("bad", ["\x00", "\x1f", "\x7f"])
    def test_still_rejects_c0_controls_and_del(self, bad):
        with pytest.raises(ValidationError):
            AuthorizeRequest(
                client_id="ok",
                redirect_uri="https://ok.example/cb",
                code_challenge=f"c{bad}c",
            )

    def test_accepts_clean_input(self):
        req = AuthorizeRequest(
            client_id="giljo-mcp-default",
            redirect_uri="https://ok.example/cb",
            code_challenge="abc123-_",
        )
        assert req.client_id == "giljo-mcp-default"


class TestTokenFieldCaps:
    @pytest.mark.parametrize("bad", FORBIDDEN_NON_C0)
    def test_rejects_c1_controls_and_line_separators(self, bad):
        with pytest.raises(HTTPException) as exc_info:
            _enforce_oauth_field_caps(client_id=f"cid{bad}end")
        assert exc_info.value.status_code == 400
        assert "invalid characters" in exc_info.value.detail

    @pytest.mark.parametrize("bad", ["\x00", "\x1f", "\x7f"])
    def test_still_rejects_c0_controls_and_del(self, bad):
        with pytest.raises(HTTPException):
            _enforce_oauth_field_caps(redirect_uri=f"a{bad}b")

    def test_accepts_clean_input(self):
        _enforce_oauth_field_caps(
            client_id="giljo-mcp-default",
            redirect_uri="https://ok.example/cb",
        )


class TestResourceIndicatorValidation:
    @pytest.mark.parametrize(
        "bad",
        [
            "https://user:pass@evil.example/mcp",
            "https://x@evil.example",
            "http://u@host/mcp",
        ],
    )
    def test_rejects_userinfo_in_authority(self, bad):
        with pytest.raises(ValueError):
            OAuthService._validate_resource_indicator(bad)

    @pytest.mark.parametrize(
        "bad",
        [
            "ftp://host/x",
            "notaurl",
            "https:///nohost",
            "//host/mcp",
        ],
    )
    def test_rejects_bad_scheme_or_missing_authority(self, bad):
        with pytest.raises(ValueError):
            OAuthService._validate_resource_indicator(bad)

    @pytest.mark.parametrize(
        "good",
        [
            "https://mcp.example.com/mcp",
            "https://host:8443/mcp",
            "http://localhost:7272/mcp",
            "https://host/mcp?x=1",
        ],
    )
    def test_accepts_canonical_and_valid_resources(self, good):
        OAuthService._validate_resource_indicator(good)
