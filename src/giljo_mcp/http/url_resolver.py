# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Public-URL resolution for FastAPI request contexts (INF-5012).

Single source of truth for "what URL do my users see?". Delegates to
request.base_url, which FastAPI/Starlette populates from X-Forwarded-*
headers when Uvicorn is run with proxy_headers=True. This works for
every deployment edition (CE localhost, CE LAN mkcert, CE customer
nginx, Demo Cloudflare Tunnel, SaaS production) without any mode
branching.
"""

import logging
import os

from fastapi import Request
from starlette.requests import Request as StarletteRequest
from starlette.types import Scope


logger = logging.getLogger(__name__)

MCP_RESOURCE_PATH = "/mcp"

# CE-localhost fallback for GILJO_PUBLIC_URL. Shared by every reader so a
# self-hosted install with no public address configured behaves identically
# everywhere (BE-9442).
GILJO_PUBLIC_URL_DEFAULT = "http://localhost:7272"

# SEC-9227h belt-and-suspenders: log-once flag for the "saas mode but no pin"
# request-time fallback. Should be unreachable in a real boot (the startup gate
# in api/startup/saas_enforcement_gate.py aborts SaaS boot without the pin),
# but an app constructed without the lifespan (unit tests) can still get here.
_saas_pin_missing_warned = False


def _saas_pinned_base_url() -> str | None:
    """SEC-9171 (#30): SaaS-only origin pin for public-URL resolution.

    In SaaS mode the canonical public host is a single known value, while
    ``request.base_url`` honors X-Forwarded-Host — an attacker-influenceable
    header when the edge passes it through (uvicorn runs with
    ``proxy_headers=True``). Emailed lifecycle links (password reset, email
    verify, account deletion) built from it would then point at an attacker
    domain. Pinning is gated on BOTH ``GILJO_MODE=saas`` AND
    ``GILJO_PUBLIC_BASE_URL`` being set, so CE/LAN self-host deployments
    (nginx, mkcert LAN, tunnel) keep the request-derived flexibility.
    """
    if os.environ.get("GILJO_MODE", "").strip().lower() != "saas":
        return None
    pinned = os.environ.get("GILJO_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not pinned:
        # SEC-9227h: should be impossible post-boot (the startup gate aborts a
        # SaaS boot without the pin), but warn — once — instead of silently
        # falling back to the Host-header-derived URL.
        global _saas_pin_missing_warned  # noqa: PLW0603 — process-wide log-once flag
        if not _saas_pin_missing_warned:
            _saas_pin_missing_warned = True
            logger.warning(
                "GILJO_MODE=saas but GILJO_PUBLIC_BASE_URL is empty at request time — "
                "falling back to request-derived base URL (Host header). The startup "
                "gate should have prevented this (SEC-9227h)."
            )
        return None
    return pinned


def get_public_url() -> str:
    """Return the configured public address of this deployment, without trailing slash.

    The request-less counterpart to :func:`get_public_base_url`, for the paths
    that have no FastAPI ``Request`` in scope — MCP tool handlers, prompt
    builders, the chain-conductor bootstrap. Those cannot derive the public
    address from ``request.base_url``, so they read ``GILJO_PUBLIC_URL``, which
    demo/cloud deployments set because the server sits behind a reverse proxy
    and its bind address (``:7272``) is not what users see.

    Normalisation mirrors the ``GILJO_PUBLIC_BASE_URL`` treatment in
    :func:`_saas_pinned_base_url` — ``.strip().rstrip("/")`` — so a pasted value
    like ``https://app.giljo.ai/`` cannot reach a caller that then appends a
    path and emits ``https://app.giljo.ai//health`` (BE-9442). An empty or
    whitespace-only value is treated as unset rather than yielding a
    path-relative URL.

    This is the ONLY place ``GILJO_PUBLIC_URL`` is read;
    ``tests/unit/test_be9442_public_url_one_accessor.py`` enforces that by
    scanning ``src/`` and ``api/``.

    Note this is a DIFFERENT variable from ``GILJO_PUBLIC_BASE_URL``, which is
    the security-critical SaaS origin pin (boot gate, Host pin, MCP audience)
    and is resolved per-request above.

    Returns:
        Base URL string like "https://app.giljo.ai" or "http://localhost:7272".
    """
    return os.environ.get("GILJO_PUBLIC_URL", "").strip().rstrip("/") or GILJO_PUBLIC_URL_DEFAULT


def get_public_base_url(request: Request) -> str:
    """
    Return the public base URL for the current request, without trailing slash.

    Honors X-Forwarded-Host / X-Forwarded-Proto via FastAPI + Uvicorn
    proxy_headers. Do NOT read the bind address from config — config values
    are the server's bind address, not its public address. The one exception
    is the SaaS origin pin (``GILJO_PUBLIC_BASE_URL``): the hosted edition's
    public address IS fixed config, and deriving it from the request would
    trust a spoofable header (SEC-9171 #30).

    Args:
        request: The incoming FastAPI Request.

    Returns:
        Base URL string like "https://mcp.example.com" or "http://localhost:7272".
    """
    pinned = _saas_pinned_base_url()
    if pinned:
        return pinned
    return str(request.base_url).rstrip("/")


def get_canonical_mcp_resource_uri(request: Request) -> str:
    """
    Return the canonical MCP resource URI for the current request (RFC 9728).

    This is the absolute, public-facing URL of the MCP transport endpoint
    (`/mcp`). Used as:
    - the `aud` claim baked into JWTs minted for MCP Bearer auth
    - the `resource` field in `/.well-known/oauth-protected-resource`
    - the audience the MCP middleware checks tokens against

    Single source of truth for "what URL identifies this MCP server" so the
    issuer and the validator can never drift.
    """
    return f"{get_public_base_url(request)}{MCP_RESOURCE_PATH}"


def get_canonical_mcp_resource_uri_from_scope(scope: Scope) -> str:
    """ASGI-scope variant of :func:`get_canonical_mcp_resource_uri`.

    The MCP Bearer middleware runs at the ASGI layer with no FastAPI Request
    object yet constructed. Wrapping the scope in a Starlette Request lets us
    reuse the same X-Forwarded-Host / X-Forwarded-Proto resolution that
    :func:`get_public_base_url` relies on — including the SaaS origin pin
    (SEC-9171 #30), so the token audience can never drift from the URL the
    issuer advertised.
    """
    pinned = _saas_pinned_base_url()
    if pinned:
        return f"{pinned}{MCP_RESOURCE_PATH}"
    request = StarletteRequest(scope)
    return f"{str(request.base_url).rstrip('/')}{MCP_RESOURCE_PATH}"
