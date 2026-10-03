# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import yaml
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
    _saas_middleware_dir = Path(__file__).parent.parent / "saas_middleware"
    if not _saas_middleware_dir.is_dir():
        logger.critical("SaaS middleware directory missing in saas mode; aborting boot")
        raise RuntimeError("saas_middleware directory is missing in saas mode")
    try:
        from api.saas_middleware import register_saas_middleware

        register_saas_middleware(app)
        logger.info("SaaS middleware registered")
    except ImportError:
        logger.critical("SaaS middleware failed to register in saas mode — aborting boot (SEC-9131 fail-loud)")
        raise


def configure_middleware(app: FastAPI) -> None:
    import api.app as _app_module

    from giljo_mcp._config_io import read_config as _read_app_config

    cors_origins = []
    config = {}

    try:
        config = _read_app_config()
        cors_origins = config.get("security", {}).get("cors", {}).get("allowed_origins", [])
        if cors_origins:
            logger.info(f"Loaded CORS origins from config.yaml security section: {cors_origins}")
    except (OSError, ValueError, KeyError, yaml.YAMLError) as e:
        logger.warning(f"Could not load CORS config from config.yaml: {e}")

    if not cors_origins:
        cors_origins_str = os.getenv("CORS_ORIGINS", "")
        if cors_origins_str.startswith("["):
            try:
                cors_origins = json.loads(cors_origins_str)
            except json.JSONDecodeError as exc:
                raise ValueError(f"CORS_ORIGINS is not valid JSON: {exc}") from exc
        elif cors_origins_str:
            cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

    if not cors_origins:
        cors_origins = [
            "http://127.0.0.1:7272",
            "http://localhost:7272",
        ]
        logger.info(f"Using default CORS origins (no wildcards): {cors_origins}")
    else:
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

    network_mode = config.get("security", {}).get("network", {}).get("mode", "localhost")
    logger.info(f"Network mode: {network_mode}")

    if network_mode in ("auto", "static"):
        try:
            from giljo_mcp.network_detector import AdapterIPDetector

            detector = AdapterIPDetector()
            ip_changed, current_ip, adapter_name = detector.detect_ip_change(config)

            if current_ip:
                frontend_port = config.get("services", {}).get("frontend", {}).get("port", 7272)
                api_port = config.get("services", {}).get("api", {}).get("port", 7272)
                adapter_origins = [
                    f"http://{current_ip}:{frontend_port}",
                    f"http://{current_ip}:{api_port}",
                    f"http://{current_ip}:5173",
                ]

                for origin in adapter_origins:
                    if origin not in cors_origins:
                        cors_origins.append(origin)
                        logger.info(f"Added CORS origin: {origin}")

                if ip_changed:
                    logger.info(f"Network adapter IP changed: {adapter_name} -> {current_ip}")
                else:
                    logger.info(f"Network adapter IP unchanged: {adapter_name} @ {current_ip}")
            elif adapter_name:
                logger.warning(f"Network adapter '{adapter_name}' disconnected - using localhost fallback")

        except ImportError:
            logger.debug("Network detector not available - skipping dynamic IP detection")
        except (RuntimeError, ValueError, OSError, KeyError) as e:
            logger.warning(f"Network IP detection failed: {e} - continuing with static CORS config")

    anthropic_connector_origins = ("https://claude.ai", "https://claude.com")
    for origin in anthropic_connector_origins:
        if origin not in cors_origins:
            cors_origins.append(origin)

    logger.info(f"Configuring CORS with origins: {cors_origins}")


    app.add_middleware(APIMetricsMiddleware)

    if _app_module.GILJO_MODE == "saas":
        _register_saas_middleware_or_raise(app)

    app.add_middleware(AuthMiddleware, auth_manager=lambda: state.auth)

    rate_limit = int(os.getenv("API_RATE_LIMIT", "300"))
    if os.getenv("DISABLE_RATE_LIMIT", "false").lower() == "true":
        logger.info("[Rate Limit] Rate limiting disabled via environment variable")
    else:
        logger.info(f"[Rate Limit] Configured at {rate_limit} requests per minute")
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=rate_limit,
            exempt_paths=["/health", "/api/health", "/api/metrics"],
        )

    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(InputValidationMiddleware)

    app.add_middleware(
        CSRFProtectionMiddleware,
        exempt_paths=[
            "/health",
            "/api/health",
            "/api/metrics",
        ],
        exempt_prefixes=[
            "/api/auth/",
            "/api/oauth/token",
            "/api/oauth/refresh",
            "/api/oauth/revoke",
            "/api/oauth/register",
            "/api/oauth/.well-known/",
            "/api/setup/",
            "/mcp",
            "/api/download/",
            "/ws",
            "/assets",
        ],
    )


    app.state.cors_origins = cors_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-API-Key",
            "X-Tenant-Key",
            "X-CSRF-Token",
            "MCP-Protocol-Version",
            "Mcp-Session-Id",
            "Mcp-Method",
            "Mcp-Name",
        ],
        expose_headers=["X-Total-Count"],
    )
