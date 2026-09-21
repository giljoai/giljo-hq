# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from api.endpoints.oauth import (
    MCP_SPEC_VERSIONS_SUPPORTED,
    OAuthMetadataResponse,
    oauth_metadata,
)
from giljo_mcp.http.url_resolver import (
    get_canonical_mcp_resource_uri,
    get_public_base_url,
)
from giljo_mcp.services.oauth_service import OAUTH_GRANTABLE_SCOPES


well_known_router = APIRouter()


class ProtectedResourceMetadataResponse(BaseModel):
    """OAuth 2.0 Protected Resource metadata (RFC 9728).

    Per RFC 8707 §3, advertises ``resource_indicators_supported: true`` so
    spec-aware clients (claude.ai connector backend) know they MUST send
    ``resource`` to /authorize and /token. API-0021d Phase 2 enforces that
    binding server-side.
    """

    resource: str
    authorization_servers: list[str]
    scopes_supported: list[str]
    bearer_methods_supported: list[str]
    resource_indicators_supported: bool = True


@well_known_router.get(
    "/.well-known/oauth-authorization-server",
    response_model=OAuthMetadataResponse,
    response_model_exclude_none=True,
    tags=["oauth"],
)
async def oauth_metadata_root_mirror(request: Request):
    """RFC 8414 root-path mirror of `/api/oauth/.well-known/oauth-authorization-server`.

    Spec-compliant clients (Claude.ai, MCP CLI tooling) probe the root path
    first. Body is identical to the `/api/oauth/...` route — same handler
    invoked for a single source of truth.
    """
    return await oauth_metadata(request)


@well_known_router.get(
    "/.well-known/oauth-protected-resource",
    response_model=ProtectedResourceMetadataResponse,
    tags=["oauth"],
)
async def oauth_protected_resource_metadata(request: Request):
    """Return OAuth 2.0 Protected Resource metadata for `/mcp` (RFC 9728).

    Tells clients which authorization server issues tokens for this resource
    and how to present them. The `WWW-Authenticate` header on `/mcp` 401s
    points here so a client that just got rejected can self-bootstrap.
    """
    return ProtectedResourceMetadataResponse(
        resource=get_canonical_mcp_resource_uri(request),
        authorization_servers=[get_public_base_url(request)],
        scopes_supported=sorted(OAUTH_GRANTABLE_SCOPES),
        bearer_methods_supported=["header"],
    )


@well_known_router.get(
    "/.well-known/oauth-protected-resource/{resource_path:path}",
    response_model=ProtectedResourceMetadataResponse,
    include_in_schema=False,
    tags=["oauth"],
)
async def oauth_protected_resource_metadata_pathsuffix(
    resource_path: str,
    request: Request,
):
    """RFC 9728 §3.1 path-suffix variant: `/.well-known/oauth-protected-resource/{path}`.

    Returns identical metadata to the host-only form for `resource_path == "mcp"`;
    404 for any other suffix. `mcp` is the only protected resource this server
    exposes — multi-resource support is out of scope (API-0021k).
    """
    if resource_path.lstrip("/") != "mcp":
        return JSONResponse(
            status_code=404,
            content={"error": "Not Found"},
        )
    return await oauth_protected_resource_metadata(request)


@well_known_router.get(
    "/.well-known/openid-configuration",
    include_in_schema=False,
    tags=["oauth"],
)
async def oidc_configuration_not_supported():
    """Return 404 for the OIDC discovery document — OIDC is not implemented."""
    return JSONResponse(
        status_code=404,
        content={"error": "OIDC not supported on this server"},
    )


class McpServerInfoResponse(BaseModel):
    """MCP spec-version + capability discovery document (API-0021h).

    Lightweight companion to OAuth AS-metadata: exposes the declared MCP
    spec-version list, the server identity, and a capability snapshot read
    from the canonical FastMCP tool registry. Surface for conformance
    discovery without forcing the client through `initialize`.
    """

    spec_versions: list[str]
    capabilities: dict
    server_name: str
    server_version: str


@well_known_router.get(
    "/.well-known/mcp-server-info",
    response_model=McpServerInfoResponse,
    tags=["oauth"],
)
async def mcp_server_info():
    """Return MCP spec-version + capability discovery document (API-0021h).

    Public, unauthenticated endpoint. Capability data is read from canonical
    sources — `TOOL_SCOPES` (defined alongside the FastMCP instance) for the
    scope-per-tool map, `giljo_mcp.__version__` for `server_version`. No
    duplicate registries.
    """
    from api.endpoints.mcp_sdk_server import TOOL_SCOPES, mcp
    from giljo_mcp import __version__ as giljo_version

    capabilities: dict = {
        "tools": {
            "count": len(TOOL_SCOPES),
            "scopes": dict(TOOL_SCOPES),
        }
    }

    return McpServerInfoResponse(
        spec_versions=list(MCP_SPEC_VERSIONS_SUPPORTED),
        capabilities=capabilities,
        server_name=mcp.name,
        server_version=giljo_version,
    )


@well_known_router.get(
    "/.well-known/openai-apps-challenge",
    response_class=PlainTextResponse,
    tags=["oauth"],
)
async def openai_apps_challenge():
    """Serve the OpenAI apps directory domain-ownership token (INF-9618).

    OpenAI verifies that you control this server's domain by fetching this
    path and expecting the body to be exactly the challenge token issued by
    their portal, as plain text. This endpoint is inert unless the operator
    sets ``GILJO_OPENAI_APPS_CHALLENGE_TOKEN``: with the variable unset or
    blank it answers 404, so nothing is exposed by default. The 404 is a
    direct response rather than a raised exception so the single-port SPA
    fallback never turns it into a 200 HTML page.
    """
    token = os.environ.get("GILJO_OPENAI_APPS_CHALLENGE_TOKEN", "").strip()
    if not token:
        return PlainTextResponse("Not Found", status_code=404, media_type="text/plain")
    return PlainTextResponse(token, media_type="text/plain")
