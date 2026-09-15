# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from api.endpoints.oauth import AuthorizeRequest
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService


TENANT_KEY = "tk_sec9451_resource"
REDIRECT_URI = "http://localhost:8080/callback"
CODE_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
VALID_RESOURCE = "https://example.com/mcp"


async def _validate(service: OAuthService, **overrides):
    params = {
        "client_id": BUILTIN_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": CODE_CHALLENGE,
        "code_challenge_method": "S256",
        "response_type": "code",
        "scope": "mcp:read mcp:write",
        "tenant_key": TENANT_KEY,
    }
    params.update(overrides)
    await service.validate_authorize_request(**params)


class TestSec9451AuthorizeRequestAffordance:

    @staticmethod
    def _payload(**overrides) -> dict:
        payload = {
            "client_id": BUILTIN_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": CODE_CHALLENGE,
            "code_challenge_method": "S256",
            "response_type": "code",
            "scope": "mcp:read mcp:write",
        }
        payload.update(overrides)
        return payload

    def test_omitted_resource_key_arrives_as_none(self):
        assert AuthorizeRequest(**self._payload()).resource is None

    def test_explicit_null_resource_also_arrives_as_none(self):
        assert AuthorizeRequest(**self._payload(resource=None)).resource is None

    def test_empty_string_resource_survives_the_model_and_reaches_the_validator(self):
        assert AuthorizeRequest(**self._payload(resource="")).resource == ""


class TestSec9451AbsentResourceIndicator:

    @pytest.mark.asyncio
    async def test_absent_resource_is_accepted(self, db_session):
        service = OAuthService(db_session=db_session)
        await _validate(service, resource=None)

    @pytest.mark.asyncio
    async def test_empty_resource_is_rejected(self, db_session):
        service = OAuthService(db_session=db_session)
        with pytest.raises(ValueError, match="resource must be a non-empty string"):
            await _validate(service, resource="")

    @pytest.mark.asyncio
    async def test_valid_resource_is_still_accepted(self, db_session):
        service = OAuthService(db_session=db_session)
        await _validate(service, resource=VALID_RESOURCE)
