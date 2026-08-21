# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for API-0021h — MCP spec-version conformance declaration.

Locks the publicly advertised MCP spec versions and the `/.well-known/mcp-server-info`
endpoint shape so future refactors cannot silently drop a declared version or
break the capability/version-discovery contract documented in CONFORMANCE.md.

Failing-layer discipline (per CLAUDE.md): every test exercises the FastAPI
route, not the handler function directly. The bug class this guards against
(silent metadata regression) lives at the HTTP boundary — that is the layer
that must be asserted.

Test categories:
- TestSpecVersionsConstant: MCP_SPEC_VERSIONS_SUPPORTED is the single source
  of truth — imported from the canonical module, not duplicated.
- TestAuthorizationServerMetadataAdvertisesSpecVersions: the AS-metadata
  response (RFC 8414, both canonical /api/oauth/.well-known/... and root mirror)
  carries `mcp_spec_versions_supported` containing every declared version.
- TestMcpServerInfoEndpoint: the new GET /.well-known/mcp-server-info returns
  declared versions, capabilities (read from canonical TOOL_SCOPES source),
  server_name, and server_version (from giljo_mcp.__version__).
"""

import pytest

from api.endpoints.oauth import MCP_SPEC_VERSIONS_SUPPORTED


# Declared list locked here as well so a refactor that mutates the constant
# fails this test even if both sides still agree. Update both intentionally.
EXPECTED_DECLARED_VERSIONS: list[str] = ["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]


class TestSpecVersionsConstant:
    """The declared-version list is the single source of truth."""

    def test_constant_matches_expected_declared_versions(self):
        assert MCP_SPEC_VERSIONS_SUPPORTED == EXPECTED_DECLARED_VERSIONS, (
            "MCP_SPEC_VERSIONS_SUPPORTED drifted from the documented declared list. "
            "Update CONFORMANCE.md alongside any change here."
        )

    def test_constant_is_immutable_shape(self):
        # The constant must be a list of plain version strings — no nested
        # structures, no objects. Downstream serializers depend on this shape.
        assert isinstance(MCP_SPEC_VERSIONS_SUPPORTED, list)
        for version in MCP_SPEC_VERSIONS_SUPPORTED:
            assert isinstance(version, str)
            # Spec versions are YYYY-MM-DD dated identifiers
            assert len(version) == 10 and version.count("-") == 2, (
                f"declared spec version not in YYYY-MM-DD form: {version!r}"
            )


class TestAuthorizationServerMetadataAdvertisesSpecVersions:
    """RFC 8414 AS-metadata MUST advertise `mcp_spec_versions_supported`."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("declared_version", EXPECTED_DECLARED_VERSIONS)
    async def test_api_oauth_route_includes_version(self, api_client, declared_version):
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200, response.text

        body = response.json()
        assert "mcp_spec_versions_supported" in body, (
            f"AS-metadata response missing mcp_spec_versions_supported claim: {body}"
        )
        assert declared_version in body["mcp_spec_versions_supported"], (
            f"declared version {declared_version} missing from "
            f"mcp_spec_versions_supported={body['mcp_spec_versions_supported']}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("declared_version", EXPECTED_DECLARED_VERSIONS)
    async def test_root_mirror_includes_version(self, api_client, declared_version):
        response = await api_client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200, response.text

        body = response.json()
        assert "mcp_spec_versions_supported" in body, body
        assert declared_version in body["mcp_spec_versions_supported"]

    @pytest.mark.asyncio
    async def test_root_mirror_body_matches_canonical_route(self, api_client):
        api_resp = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        root_resp = await api_client.get("/.well-known/oauth-authorization-server")
        assert api_resp.status_code == 200
        assert root_resp.status_code == 200
        assert api_resp.json() == root_resp.json(), (
            "root mirror body must match /api/oauth/.well-known/oauth-authorization-server "
            "(single source of truth invariant)"
        )

    @pytest.mark.asyncio
    async def test_advertised_list_matches_constant(self, api_client):
        response = await api_client.get("/api/oauth/.well-known/oauth-authorization-server")
        body = response.json()
        assert body["mcp_spec_versions_supported"] == MCP_SPEC_VERSIONS_SUPPORTED, (
            "AS-metadata advertised list diverged from MCP_SPEC_VERSIONS_SUPPORTED"
        )


class TestMcpServerInfoEndpoint:
    """`GET /.well-known/mcp-server-info` is the conformance discovery surface."""

    @pytest.mark.asyncio
    async def test_endpoint_returns_200(self, api_client):
        response = await api_client.get("/.well-known/mcp-server-info")
        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_response_shape_contains_required_top_level_keys(self, api_client):
        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        for required_key in ("spec_versions", "capabilities", "server_name", "server_version"):
            assert required_key in body, f"missing required key {required_key!r}: {body}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("declared_version", EXPECTED_DECLARED_VERSIONS)
    async def test_spec_versions_contains_each_declared_version(self, api_client, declared_version):
        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        assert declared_version in body["spec_versions"], (
            f"declared version {declared_version} missing from server-info spec_versions"
        )

    @pytest.mark.asyncio
    async def test_spec_versions_matches_constant(self, api_client):
        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        assert body["spec_versions"] == MCP_SPEC_VERSIONS_SUPPORTED, (
            "server-info spec_versions diverged from MCP_SPEC_VERSIONS_SUPPORTED"
        )

    @pytest.mark.asyncio
    async def test_server_name_is_giljo_hq(self, api_client):
        from giljo_mcp import branding

        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        # The MCP server is registered as `name=branding.MCP_ALIAS` in FastMCP
        # (see api/endpoints/mcp_tools/_base.py). The server_name field must
        # match that identity exactly (BE-9275a: alias flipped to giljo_hq).
        assert body["server_name"] == branding.MCP_ALIAS, (
            f"server_name must match the FastMCP registered name, got {body['server_name']!r}"
        )

    @pytest.mark.asyncio
    async def test_server_version_matches_canonical_version(self, api_client):
        from giljo_mcp import __version__ as giljo_version

        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        assert body["server_version"] == giljo_version, (
            f"server_version must equal giljo_mcp.__version__ ({giljo_version!r}), got {body['server_version']!r}"
        )

    @pytest.mark.asyncio
    async def test_capabilities_reads_from_tool_scopes_source(self, api_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        capabilities = body["capabilities"]
        assert isinstance(capabilities, dict), f"capabilities must be a dict, got {type(capabilities).__name__}"
        # The endpoint must expose a `tools` block — at minimum a count and
        # the per-tool scope map. Both are derivable from TOOL_SCOPES, the
        # canonical source.
        assert "tools" in capabilities, f"capabilities.tools missing: {capabilities}"
        tools_block = capabilities["tools"]
        assert "count" in tools_block, f"capabilities.tools.count missing: {tools_block}"
        assert tools_block["count"] == len(TOOL_SCOPES), (
            "capabilities.tools.count drifted from TOOL_SCOPES registry — "
            "endpoint must read from the canonical source, not a hardcoded list"
        )

    @pytest.mark.asyncio
    async def test_capabilities_includes_each_tool_scope_mapping(self, api_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        response = await api_client.get("/.well-known/mcp-server-info")
        body = response.json()
        scopes_block = body["capabilities"]["tools"].get("scopes", {})
        for tool_name, scope in TOOL_SCOPES.items():
            assert scopes_block.get(tool_name) == scope, (
                f"capabilities.tools.scopes[{tool_name!r}] must be {scope!r} (from canonical TOOL_SCOPES)"
            )
