# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
from pathlib import Path

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger(__name__)

CSP_SCRIPT_HASH_1 = "'sha256-LRJOHmw/kARrWFQNFXTam7BNVjtucN2V1FzuxKtEUg0='"
CSP_SCRIPT_HASH_2 = "'sha256-T+y4FnL+BP2aiGWNs6H5HdyLosVMnGaNc9v+5DaNNJM='"

STATIC_MEDIA_MAX_AGE_SECONDS = 86400
STATIC_MEDIA_CACHE_CONTROL = f"public, max-age={STATIC_MEDIA_MAX_AGE_SECONDS}"
_STATIC_MEDIA_CONTENT_TYPES = ("image/", "font/")

_EXTRA_CSP_SCRIPT_HASHES: set[str] = set()
_EXTRA_CSP_STYLE_HASHES: set[str] = set()
_EXTRA_CSP_STYLE_ORIGINS: set[str] = set()
_EXTRA_CSP_SCRIPT_ORIGINS: set[str] = set()
_EXTRA_CSP_CONNECT_ORIGINS: set[str] = set()
_EXTRA_CSP_FRAME_ORIGINS: set[str] = set()
_EXTRA_CSP_PAYMENT_ORIGINS: set[str] = set()
_ALLOW_EXTRA_STYLE_ATTRS: list[bool] = [False]


def register_csp_sources(
    *,
    script_hashes: list[str] | tuple[str, ...] = (),
    style_hashes: list[str] | tuple[str, ...] = (),
    style_origins: list[str] | tuple[str, ...] = (),
    script_origins: list[str] | tuple[str, ...] = (),
    connect_origins: list[str] | tuple[str, ...] = (),
    frame_origins: list[str] | tuple[str, ...] = (),
    payment_origins: list[str] | tuple[str, ...] = (),
    allow_style_attrs: bool = False,
) -> None:
    _EXTRA_CSP_SCRIPT_HASHES.update(_clean_values(script_hashes))
    _EXTRA_CSP_STYLE_HASHES.update(_clean_values(style_hashes))
    _EXTRA_CSP_STYLE_ORIGINS.update(_clean_values(style_origins))
    _EXTRA_CSP_SCRIPT_ORIGINS.update(_clean_values(script_origins))
    _EXTRA_CSP_CONNECT_ORIGINS.update(_clean_values(connect_origins))
    _EXTRA_CSP_FRAME_ORIGINS.update(_clean_values(frame_origins))
    _EXTRA_CSP_PAYMENT_ORIGINS.update(_clean_values(payment_origins))
    _ALLOW_EXTRA_STYLE_ATTRS[0] = _ALLOW_EXTRA_STYLE_ATTRS[0] or allow_style_attrs


def clear_registered_csp_sources_for_tests() -> None:
    _EXTRA_CSP_SCRIPT_HASHES.clear()
    _EXTRA_CSP_STYLE_HASHES.clear()
    _EXTRA_CSP_STYLE_ORIGINS.clear()
    _EXTRA_CSP_SCRIPT_ORIGINS.clear()
    _EXTRA_CSP_CONNECT_ORIGINS.clear()
    _EXTRA_CSP_FRAME_ORIGINS.clear()
    _EXTRA_CSP_PAYMENT_ORIGINS.clear()
    _ALLOW_EXTRA_STYLE_ATTRS[0] = False


def _clean_values(values: list[str] | tuple[str, ...]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


def _frontend_dist_built() -> bool:
    return (Path.cwd() / "frontend" / "dist" / "index.html").exists()


def is_development_mode() -> bool:
    env = os.getenv("GILJO_ENV", "").lower()
    if env in ("dev", "development"):
        return True

    env = os.getenv("ENVIRONMENT", "").lower()
    if env in ("dev", "development"):
        return not _frontend_dist_built()

    return False


class SecurityHeadersMiddleware:

    def __init__(self, app: ASGIApp, hsts_max_age: int = 31536000):
        self.app = app
        self.hsts_max_age = hsts_max_age
        self.is_dev = is_development_mode()

        self.external_host = None
        self.api_port = None
        try:
            from giljo_mcp.config_manager import get_config

            config = get_config()
            self.external_host = config.get_nested("services.external_host", default=None)
            self.api_port = config.get_nested("services.api.port", default=config.server.api_port)
        except (ImportError, AttributeError, KeyError, TypeError):
            logger.debug("Config not available for CSP — using defaults")

        self.sentry_origins: list[str] = self._compute_sentry_origins()
        if self.sentry_origins:
            logger.info(f"CSP: sentry ingest allowlisted in connect-src: {self.sentry_origins}")

        mode_str = "DEVELOPMENT" if self.is_dev else "PRODUCTION"
        logger.info(f"SecurityHeadersMiddleware initialized in {mode_str} mode")
        logger.info(f"HSTS max-age: {hsts_max_age}s")

        if self.is_dev:
            logger.warning("CSP: unsafe-eval enabled for development HMR")

    @staticmethod
    def _compute_sentry_origins() -> list[str]:
        from api.app_state import GILJO_MODE

        is_saas = GILJO_MODE == "saas"
        if not is_saas:
            return []
        from urllib.parse import urlparse

        origins: list[str] = []
        for var in ("SENTRY_DSN_BACKEND", "SENTRY_DSN_FRONTEND"):
            dsn = os.getenv(var, "").strip()
            if not dsn:
                continue
            try:
                parsed = urlparse(dsn)
            except ValueError:
                continue
            if parsed.scheme not in ("http", "https"):
                continue
            if not parsed.hostname:
                continue
            origin = f"{parsed.scheme}://{parsed.hostname}"
            if origin not in origins:
                origins.append(origin)
        return origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                self._apply_security_headers(MutableHeaders(raw=message["headers"]), request, message["status"])
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _apply_security_headers(self, response_headers: MutableHeaders, request: Request, status: int) -> None:
        if request.url.scheme == "https":
            response_headers["Strict-Transport-Security"] = f"max-age={self.hsts_max_age}; includeSubDomains; preload"

        script_hashes = " ".join([CSP_SCRIPT_HASH_1, CSP_SCRIPT_HASH_2, *_EXTRA_CSP_SCRIPT_HASHES])
        script_src = f"'self' {script_hashes} https://static.cloudflareinsights.com"
        if _EXTRA_CSP_SCRIPT_ORIGINS:
            script_src += " " + " ".join(sorted(_EXTRA_CSP_SCRIPT_ORIGINS))
        if self.is_dev:
            script_src += " 'unsafe-eval'"

        nonce = getattr(request.state, "csp_nonce", "")
        style_hashes = "".join(f" {h}" for h in sorted(_EXTRA_CSP_STYLE_HASHES))
        style_src = f"'self' 'nonce-{nonce}'{style_hashes}" if nonce else "'self' 'unsafe-inline'"
        if _EXTRA_CSP_STYLE_ORIGINS:
            style_src += " " + " ".join(sorted(_EXTRA_CSP_STYLE_ORIGINS))

        connect_src = "'self' ws: wss: https://cloudflareinsights.com"
        if self.sentry_origins:
            connect_src += " " + " ".join(self.sentry_origins)
        if _EXTRA_CSP_CONNECT_ORIGINS:
            connect_src += " " + " ".join(sorted(_EXTRA_CSP_CONNECT_ORIGINS))

        frame_src = "'self'"
        if _EXTRA_CSP_FRAME_ORIGINS:
            frame_src += " " + " ".join(sorted(_EXTRA_CSP_FRAME_ORIGINS))

        style_src_attr_directive = "style-src-attr 'unsafe-inline'; " if _ALLOW_EXTRA_STYLE_ATTRS[0] else ""

        response_headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src {script_src}; "
            f"style-src {style_src}; "
            f"{style_src_attr_directive}"
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            f"connect-src {connect_src}; "
            f"frame-src {frame_src}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

        response_headers["X-Frame-Options"] = "DENY"

        response_headers["X-Content-Type-Options"] = "nosniff"

        response_headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        payment_policy = "payment=()"
        if _EXTRA_CSP_PAYMENT_ORIGINS:
            origins = " ".join(f'"{o}"' for o in sorted(_EXTRA_CSP_PAYMENT_ORIGINS))
            payment_policy = f"payment=(self {origins})"
        response_headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            f"{payment_policy}, "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )

        response_headers["X-XSS-Protection"] = "1; mode=block"

        path = request.url.path
        is_asset = path.startswith("/assets/")
        serves_the_asset = 200 <= status < 300 or status == 304

        if is_asset and not serves_the_asset:
            response_headers["Cache-Control"] = "no-store"
        elif "cache-control" not in (h.lower() for h in response_headers):
            if is_asset:
                response_headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                content_type = response_headers.get("content-type", "")
                if content_type.startswith("text/html"):
                    response_headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                    response_headers["Pragma"] = "no-cache"
                    response_headers["Expires"] = "0"
                elif (
                    serves_the_asset
                    and content_type.startswith(_STATIC_MEDIA_CONTENT_TYPES)
                    and not path.startswith("/api")
                ):
                    response_headers["Cache-Control"] = STATIC_MEDIA_CACHE_CONTROL
