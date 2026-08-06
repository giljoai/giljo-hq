# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9227i (L2 + L3) — OAuth log-injection / resource-validation hardening.

L2 — the two OAuth field guards (``AuthorizeRequest._no_control_chars`` field
validator on /authorize, and ``_enforce_oauth_field_caps`` on /token) rejected
C0 controls + DEL but let C1 controls (0x80-0x9F) and the Unicode line/paragraph
separators (U+2028/U+2029) through — all can smuggle a line break or terminal
escape into a log line (CWE-117). Both guards now route through one shared
``_has_forbidden_log_chars`` helper so they cannot drift again (the drift itself
was the finding).

L3 — ``OAuthService._validate_resource_indicator`` accepted an RFC 8707 resource
via a ``startswith(("https://","http://"))`` PREFIX check, so odd authorities
like ``https://user:pass@evil/`` slipped through. It now parses with urllib:
scheme in {http,https}, non-empty netloc, no userinfo. The canonical MCP
resource URI (``get_canonical_mcp_resource_uri``, shape ``https://host/mcp``)
must keep validating — guarded below.

Failing layer: the guard functions themselves (pure, no DB) — the exact layer
each finding lives at. Parallel-safe: no shared state, no DB, no env.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.endpoints.oauth import AuthorizeRequest, _enforce_oauth_field_caps
from giljo_mcp.services.oauth_service import OAuthService


# C1 controls + the Unicode line (U+2028) and paragraph (U+2029) separators.
# Built with chr() so the source file carries no invisible bytes.
FORBIDDEN_NON_C0 = ["\x80", "\x85", "\x9f", chr(0x2028), chr(0x2029)]


# --------------------------------------------------------------------------
# L2 — /authorize field validator (`_no_control_chars`)
# --------------------------------------------------------------------------
class TestAuthorizeFieldValidator:
    @pytest.mark.parametrize("bad", FORBIDDEN_NON_C0)
    def test_rejects_c1_controls_and_line_separators(self, bad):
        # FAIL-FIRST: pre-fix these chars pass the < 32 / == 0x7F check.
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


# --------------------------------------------------------------------------
# L2 — /token field-caps guard (`_enforce_oauth_field_caps`)
# --------------------------------------------------------------------------
class TestTokenFieldCaps:
    @pytest.mark.parametrize("bad", FORBIDDEN_NON_C0)
    def test_rejects_c1_controls_and_line_separators(self, bad):
        # FAIL-FIRST: pre-fix these chars pass the < 32 / == 0x7F check.
        with pytest.raises(HTTPException) as exc_info:
            _enforce_oauth_field_caps(client_id=f"cid{bad}end")
        assert exc_info.value.status_code == 400
        assert "invalid characters" in exc_info.value.detail

    @pytest.mark.parametrize("bad", ["\x00", "\x1f", "\x7f"])
    def test_still_rejects_c0_controls_and_del(self, bad):
        with pytest.raises(HTTPException):
            _enforce_oauth_field_caps(redirect_uri=f"a{bad}b")

    def test_accepts_clean_input(self):
        # No raise for clean values (the happy path is load-bearing).
        _enforce_oauth_field_caps(
            client_id="giljo-mcp-default",
            redirect_uri="https://ok.example/cb",
        )


# --------------------------------------------------------------------------
# L3 — RFC 8707 resource-indicator validation
# --------------------------------------------------------------------------
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
        # FAIL-FIRST: pre-fix the prefix check accepts these.
        with pytest.raises(ValueError):
            OAuthService._validate_resource_indicator(bad)

    @pytest.mark.parametrize(
        "bad",
        [
            "ftp://host/x",
            "notaurl",
            "https:///nohost",  # empty authority
            "//host/mcp",  # no scheme
        ],
    )
    def test_rejects_bad_scheme_or_missing_authority(self, bad):
        with pytest.raises(ValueError):
            OAuthService._validate_resource_indicator(bad)

    @pytest.mark.parametrize(
        "good",
        [
            "https://mcp.example.com/mcp",  # canonical shape
            "https://host:8443/mcp",  # explicit port
            "http://localhost:7272/mcp",  # localhost dev
            "https://host/mcp?x=1",  # query allowed (RFC 8707)
        ],
    )
    def test_accepts_canonical_and_valid_resources(self, good):
        # REGRESSION: the canonical MCP resource URI must keep validating.
        OAuthService._validate_resource_indicator(good)
