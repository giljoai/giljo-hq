# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9451: an ABSENT RFC 8707 resource indicator is not an EMPTY one.

`OAuthService.validate_authorize_request` guards the indicator with
``if resource is not None: self._validate_resource_indicator(resource)``, and
that validator's first line rejects any falsy value. So the contract is
asymmetric on purpose:

  * ``None``  -> accepted (the client did not request a specific resource)
  * ``""``    -> rejected, 400 at the route layer

The consent SPA used to collapse an absent query param into ``""`` before
POSTing it, manufacturing the one value this method refuses and making
claude.ai's connect fail on production with
``OAuth authorize validation failed: resource must be a non-empty string``.
The frontend half is pinned in
``frontend/tests/saas/OAuthAuthorizeResourceForward.spec.js``; the contract
that fix depends on is pinned HERE, because the frontend assertion that
originally covered this case asserted the empty string was acceptable and so
locked the defect in as expected behaviour.

Both directions are pinned deliberately: a client that sends a valid resource
must still have it validated and forwarded (the API-0021d F2 incident, commit
308363c90 — dropping that forwarding fails the /token exchange with 401
invalid_grant), and a client that sends none must succeed.
"""

import pytest

from api.endpoints.oauth import AuthorizeRequest
from giljo_mcp.services.oauth_service import BUILTIN_CLIENT_ID, OAuthService


TENANT_KEY = "tk_sec9451_resource"
REDIRECT_URI = "http://localhost:8080/callback"
CODE_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
VALID_RESOURCE = "https://example.com/mcp"


async def _validate(service: OAuthService, **overrides):
    """Run a valid authorize request, overriding only what a test varies."""
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
    """The route-model affordance the frontend was defeating.

    ``AuthorizeRequest.resource`` is ``str | None = Field(default=None, ...)``
    and its comment states the intent outright: *"Optional during the
    API-0021d transition window so older clients that don't yet forward
    `resource` still complete /authorize."* The absent case was anticipated
    and deliberately supported.

    Collapsing an absent query param into ``""`` made that default
    unreachable — the key was always present, so it never fired. These pin
    the affordance itself rather than the frontend's choice of sentinel, so
    reintroducing an empty string at ANY layer fails here too.
    """

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
        """A body with no `resource` key at all must reach the service as None.

        This is the link between the frontend fix and the backend contract:
        the SPA omits the key, and `default=None` is what turns that into the
        value the validator accepts.
        """
        assert AuthorizeRequest(**self._payload()).resource is None

    def test_explicit_null_resource_also_arrives_as_none(self):
        """`resource: null` is equivalent to omitting it — the field is `str | None`.

        Pinned so the fix is not brittle to whether the client serializes the
        absent case as an omitted key or an explicit null.
        """
        assert AuthorizeRequest(**self._payload(resource=None)).resource is None

    def test_empty_string_resource_survives_the_model_and_reaches_the_validator(self):
        """The route model does NOT coerce `""` to None — the service rejects it.

        This is why the defect was fatal rather than absorbed: nothing between
        the SPA and `_validate_resource_indicator` normalises an empty string.
        If this assertion ever flips, the empty-vs-absent distinction has moved
        and `test_empty_resource_is_rejected` below should be revisited with it.
        """
        assert AuthorizeRequest(**self._payload(resource="")).resource == ""


class TestSec9451AbsentResourceIndicator:
    """The absent/empty asymmetry that broke the claude.ai connector."""

    @pytest.mark.asyncio
    async def test_absent_resource_is_accepted(self, db_session):
        """No resource indicator at all must pass — claude.ai sends none.

        This is the direction production was failing on 2026-08-16.
        """
        service = OAuthService(db_session=db_session)
        await _validate(service, resource=None)

    @pytest.mark.asyncio
    async def test_empty_resource_is_rejected(self, db_session):
        """An empty string is NOT a synonym for absent — it is a hard error.

        This is the assertion that makes the frontend fix load-bearing: if
        this ever starts passing, the SPA collapsing absent into ``""`` would
        stop being fatal and the real contract would have moved.
        """
        service = OAuthService(db_session=db_session)
        with pytest.raises(ValueError, match="resource must be a non-empty string"):
            await _validate(service, resource="")

    @pytest.mark.asyncio
    async def test_valid_resource_is_still_accepted(self, db_session):
        """API-0021d F2 direction: a real indicator must still validate.

        The SEC-9451 fix changes only the absent-value default, so a client
        that DOES send a resource keeps having it forwarded and bound.
        """
        service = OAuthService(db_session=db_session)
        await _validate(service, resource=VALID_RESOURCE)
