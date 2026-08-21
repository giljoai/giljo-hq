# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Middleware wiring extracted from api/app.py.

Behavior-preserving (BE-6042b): ``configure_middleware(app)`` adds the exact
same middleware in the exact same order as the original module-level
``_configure_middleware``. Order is security-load-bearing — middleware is added
in reverse order of execution (last added = first executed).

The SaaS gate reads ``GILJO_MODE`` from the ``api.app`` module namespace at call
time (``import api.app`` deferred into the function body) so existing tests that
``patch("api.app.GILJO_MODE", ...)`` continue to drive the conditional exactly as
before the split.
"""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app_state import state
from api.middleware import (
    APIMetricsMiddleware,
    AuthMiddleware,
    CSRFProtectionMiddleware,
    InputValidationMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


logger = logging.getLogger("api.app")


def _register_saas_middleware_or_raise(app: FastAPI) -> None:
    """Register the SaaS middleware stack, failing LOUD in saas mode (SEC-9131 / BE-6069).

    Caller has already confirmed saas mode. Reached only with the (present)
    ``saas_middleware`` dir, so an ImportError means the enforcement stack is broken —
    abort boot rather than ship enforcement silently absent (BE-6069). CE never reaches
    here (the dir is stripped on export, and the caller gates on saas mode).
    """
    _saas_middleware_dir = Path(__file__).parent.parent / "saas_middleware"
    if not _saas_middleware_dir.is_dir():
        return
    try:
        from api.saas_middleware import register_saas_middleware

        register_saas_middleware(app)
        logger.info("SaaS middleware registered")
    except ImportError:
        logger.critical("SaaS middleware failed to register in saas mode — aborting boot (SEC-9131 fail-loud)")
        raise


def configure_middleware(app: FastAPI) -> None:
    """Configure all middleware for the FastAPI application.

    Sets up CORS, security headers, rate limiting, authentication,
    CSRF protection, input validation, and API metrics middleware.
    Middleware is added in reverse order of execution (last added = first executed).
    """
    # GILJO_MODE is resolved through the api.app namespace at call time so that
    # tests patching ``api.app.GILJO_MODE`` continue to drive the SaaS gate.
    import api.app as _app_module

    # Configure CORS - use explicit origins from config.yaml security section
    from giljo_mcp._config_io import read_config as _read_app_config

    cors_origins = []
    config = {}  # Default to empty dict so config.get() is safe if read fails

    # Try to load from config.yaml security section
    try:
        config = _read_app_config()
        cors_origins = config.get("security", {}).get("cors", {}).get("allowed_origins", [])
        if cors_origins:
            logger.info(f"Loaded CORS origins from config.yaml security section: {cors_origins}")
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f"Could not load CORS config from config.yaml: {e}")

    # Fallback to environment variable (for backwards compatibility)
    if not cors_origins:
        cors_origins_str = os.getenv("CORS_ORIGINS", "")
        if cors_origins_str:
            # Parse CORS origins (handle both comma-separated and JSON array formats)
            if cors_origins_str.startswith("["):
                # JSON array format from installer
                import json

                with suppress(json.JSONDecodeError):
                    cors_origins = json.loads(cors_origins_str)
            else:
                # Comma-separated format
                cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

    # Safe default: explicit localhost origins only (no wildcards)
    if not cors_origins:
        cors_origins = [
            "http://127.0.0.1:7272",
            "http://localhost:7272",
        ]
        logger.info(f"Using default CORS origins (no wildcards): {cors_origins}")
    else:
        # Reject wildcard patterns for security
        safe_origins = [origin for origin in cors_origins if "*" not in origin]
        if len(safe_origins) < len(cors_origins):
            logger.warning("CORS wildcard entries removed from config — only explicit origins are allowed")
            cors_origins = (
                safe_origins
                if safe_origins
                else [
                    "http://127.0.0.1:7272",
                    "http://localhost:7272",
                ]
            )

    # Dynamic network adapter IP detection for CORS updates
    network_mode = config.get("security", {}).get("network", {}).get("mode", "localhost")
    logger.info(f"Network mode: {network_mode}")

    if network_mode in ("auto", "static"):
        try:
            from giljo_mcp.network_detector import AdapterIPDetector

            detector = AdapterIPDetector()
            ip_changed, current_ip, adapter_name = detector.detect_ip_change(config)

            if current_ip:
                # Add adapter IP to CORS origins (whether changed or not)
                frontend_port = config.get("services", {}).get("frontend", {}).get("port", 7272)
                api_port = config.get("services", {}).get("api", {}).get("port", 7272)
                adapter_origins = [
                    f"http://{current_ip}:{frontend_port}",
                    f"http://{current_ip}:{api_port}",  # API port for direct access
                    f"http://{current_ip}:5173",  # Vite dev server
                ]

                # Add if not already present
                for origin in adapter_origins:
                    if origin not in cors_origins:
                        cors_origins.append(origin)
                        logger.info(f"Added CORS origin: {origin}")

                if ip_changed:
                    logger.info(f"Network adapter IP changed: {adapter_name} -> {current_ip}")
                else:
                    logger.info(f"Network adapter IP unchanged: {adapter_name} @ {current_ip}")
            # Adapter disconnected - log warning and fall back to localhost
            elif adapter_name:
                logger.warning(f"Network adapter '{adapter_name}' disconnected - using localhost fallback")

        except ImportError:
            logger.debug("Network detector not available - skipping dynamic IP detection")
        except (RuntimeError, ValueError, OSError, KeyError) as e:
            logger.warning(f"Network IP detection failed: {e} - continuing with static CORS config")

    # Add HTTPS origin variants when SSL is enabled
    ssl_enabled = config.get("features", {}).get("ssl_enabled", False)
    if ssl_enabled:
        https_origins = []
        for origin in cors_origins.copy():
            if origin.startswith("http://"):
                https_variant = "https://" + origin[len("http://") :]
                if https_variant not in cors_origins:
                    https_origins.append(https_variant)
        if https_origins:
            cors_origins.extend(https_origins)
            logger.info(f"Added HTTPS CORS origins for SSL mode: {https_origins}")

    # API-0021d F4: Anthropic connector first-party origins (claude.ai +
    # claude.com). Hardcoded as a defensive fallback so a future config.yaml
    # typo or deploy regression cannot drop them and silently break the
    # claude connector handshake. The values are first-party and stable per
    # Anthropic's published connector docs; admins can still extend the
    # allowlist via config.yaml — duplicates are filtered below.
    anthropic_connector_origins = ("https://claude.ai", "https://claude.com")
    for origin in anthropic_connector_origins:
        if origin not in cors_origins:
            cors_origins.append(origin)

    logger.info(f"Configuring CORS with origins: {cors_origins}")

    # Add middleware in reverse order of execution
    # (last middleware added = first middleware executed in request chain)

    # Add API metrics middleware (executes after auth — needs tenant_key from request.state)
    app.add_middleware(APIMetricsMiddleware)

    # SaaS enforcement middleware registration (conditional) — BE-6069.
    # CRITICAL ORDERING: registered HERE, before AuthMiddleware is added. Under
    # Starlette's reverse execution (last added = first executed) that makes the
    # SaaS guards run AFTER AuthMiddleware populates request.state.tenant_key, so
    # LicenseEnforcement can resolve the tenant/plan and actually enforce.
    # Pre-BE-6069 these were registered AFTER Auth (below CORS), which made them
    # execute BEFORE Auth — every guard read an unset tenant_key and silently
    # no-opped, so license-lapse and trial-expiry write enforcement were dead.
    # Follows Section F of docs/EDITION_ISOLATION_GUIDE.md.
    if _app_module.GILJO_MODE == "saas":
        _register_saas_middleware_or_raise(app)

    # Add authentication middleware (sets request.state.tenant_key for downstream middleware)
    app.add_middleware(AuthMiddleware, auth_manager=lambda: state.auth)

    # Add rate limiting middleware (executes 4th - protects endpoints, 60 requests/minute for LAN security)
    # Rate limiting configuration
    # Development: Higher limit or disabled via environment variable
    # Production: Standard 60 requests per minute
    rate_limit = int(os.getenv("API_RATE_LIMIT", "300"))  # Default 300 for development
    if os.getenv("DISABLE_RATE_LIMIT", "false").lower() == "true":
        logger.info("[Rate Limit] Rate limiting disabled via environment variable")
    else:
        logger.info(f"[Rate Limit] Configured at {rate_limit} requests per minute")
        # STABILITY (perf-findings #2): bare ``/health`` is the platform healthcheck
        # path AND the frontend liveness probe, but the limiter's DEFAULT exempt list is
        # only ["/api/health", "/api/metrics"] — so under a saturated bucket /health
        # 429s, and the platform marks the app unhealthy and restarts it. (The ["/health", ...]
        # list a few lines below is wired to CSRFProtectionMiddleware, NOT here.)
        # Pass /health explicitly so it always bypasses rate limiting.
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=rate_limit,
            exempt_paths=["/health", "/api/health", "/api/metrics"],
        )

    # Add security headers middleware (executes 3rd - adds security headers to all responses)
    # Handover 0129c: Enhanced security headers (HSTS, CSP, X-Frame-Options, etc.)
    app.add_middleware(SecurityHeadersMiddleware)

    # Add input validation middleware (executes 3rd - validates query params, blocks malicious input)
    # Handover 0129c: Protection against SQL injection, XSS, path traversal
    app.add_middleware(InputValidationMiddleware, strict_mode=False)

    # CSRF protection middleware (executes after auth, before route handlers)
    # Handover 0765f: Enabled with double-submit cookie pattern
    app.add_middleware(
        CSRFProtectionMiddleware,
        exempt_paths=[
            "/health",
            "/api/health",
            "/api/metrics",
        ],
        exempt_prefixes=[
            "/api/auth/",  # Auth endpoints (login, register, refresh — no CSRF cookie yet)
            "/api/oauth/token",  # OAuth token exchange (external MCP clients, PKCE-protected)
            "/api/oauth/refresh",  # OAuth refresh-token grant (external MCP clients, secret-protected)
            "/api/oauth/revoke",  # RFC 7009 revocation (external MCP clients, token IS the credential)
            "/api/oauth/register",  # CE RFC 7591 DCR (external MCP clients, no cookie — BE-6235)
            "/api/oauth/.well-known/",  # OAuth metadata (public GET)
            "/api/setup/",  # Setup wizard (runs before auth is configured)
            "/mcp",  # MCP-over-HTTP (API key auth, not cookie-based)
            "/api/download/",  # Public download endpoints
            "/ws",  # WebSocket endpoints
            "/assets",  # Static file assets (production frontend serving)
        ],
    )

    # v3.0: Setup mode middleware removed - unified authentication for all endpoints
    # SaaS enforcement middleware (license/trial/rate-limit) is registered earlier
    # — before AuthMiddleware — so it executes AFTER Auth populates request.state
    # (see the BE-6069 note above APIMetricsMiddleware).

    # API-0203: expose the finalized CORS allowlist on app.state so request
    # handlers can validate a same-site Origin header without re-deriving it
    # (used by the SaaS checkout endpoint to pick a trusted embed_origin).
    # Edition-neutral, additive — CE never reads it, so the Deletion Test holds.
    app.state.cors_origins = cors_origins

    # Add CORS middleware (executes 1st - MUST be first to handle OPTIONS preflight requests)
    # This MUST execute before all other middleware to add CORS headers to OPTIONS responses
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # API-0021d F5: MCP-Protocol-Version + Mcp-Session-Id are MCP
        # Streamable HTTP spec headers (2025-06-18 §"Protocol Version
        # Header"). Without them the browser preflight to /mcp returns 400
        # before the spec request reaches the auth middleware.
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-API-Key",
            "X-Tenant-Key",
            "X-CSRF-Token",
            "MCP-Protocol-Version",
            "Mcp-Session-Id",
            # INF-9371: the 2026-07-28 era carries the method (and, for tools/call,
            # the tool name) in headers as well as the body; the SDK rejects a
            # mismatch with JSON-RPC -32020. Without these a browser preflight
            # fails before the request reaches the auth middleware.
            # NOTE: the spec's `Mcp-Param-*` family cannot be expressed here --
            # CORS allow-lists are exact-match, with no prefix wildcard. Nothing in
            # our surface needs it today; a browser client that does would need a
            # deliberate decision, not a silent widening of this list.
            "Mcp-Method",
            "Mcp-Name",
        ],
        # BE-6076: the dashboard projects-list reads the filtered total from the
        # X-Total-Count response header (v-data-table :items-length). Expose it so
        # JS can read it even when the dashboard is served cross-origin. Same-origin
        # deployments can read it regardless; this just keeps it topology-proof.
        expose_headers=["X-Total-Count"],
    )
