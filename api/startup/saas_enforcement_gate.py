# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib
import logging
import os
from urllib.parse import urlsplit


logger = logging.getLogger("api.app")


def register_saas_tenant_scoped_models(*, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    try:
        importlib.import_module("giljo_mcp.saas.tenant_registration").register_saas_tenant_scoped_models()
        logger.info("SaaS tenant-scoped models registered")
    except Exception:
        logger.critical(
            "SaaS Phase 8.6 [saas_tenant_registration] failed — aborting boot "
            "(SEC-9131 fail-loud): tenant-scope widening must never be silently absent."
        )
        raise


def require_public_base_url(*, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    pinned = os.environ.get("GILJO_PUBLIC_BASE_URL", "").strip()
    if not pinned:
        logger.critical(
            "SaaS boot requires GILJO_PUBLIC_BASE_URL — aborting boot (SEC-9131 fail-loud): "
            "the OAuth issuer/audience and emailed lifecycle links must never derive from "
            "the Host header (SEC-9227h / SEC-9171 #30). Set GILJO_PUBLIC_BASE_URL to the "
            "canonical public origin, e.g. https://app.example.com"
        )
        raise RuntimeError("GILJO_PUBLIC_BASE_URL is required in SaaS mode (SEC-9227h)")
    problem = _public_base_url_problem(pinned)
    if problem:
        logger.critical(
            "GILJO_PUBLIC_BASE_URL is malformed (%s): %r — aborting boot (SEC-9131 fail-loud): "
            "a malformed origin pin is as unsafe as a missing one (SEC-9227h).",
            problem,
            pinned,
        )
        raise RuntimeError(f"GILJO_PUBLIC_BASE_URL is malformed ({problem}) (SEC-9227h)")


def _public_base_url_problem(pinned: str) -> str | None:
    try:
        parts = urlsplit(pinned)
        hostname = parts.hostname
        has_credentials = bool(parts.username or parts.password)
    except ValueError:
        return "not a parseable URL"
    if parts.scheme not in ("https", "http"):
        return "scheme must be https://"
    if not hostname:
        return "no hostname"
    if parts.scheme == "http" and hostname not in ("localhost", "127.0.0.1", "::1"):
        return "http:// is only allowed for localhost"
    if has_credentials:
        return "must not contain credentials"
    if parts.path not in ("", "/"):
        return "must not contain a path"
    if parts.query or parts.fragment:
        return "must not contain a query or fragment"
    return None


def register_mcp_subscription_gate(*, giljo_mode: str) -> None:
    is_saas = giljo_mode == "saas"
    if not is_saas:
        return
    try:
        importlib.import_module("giljo_mcp.saas.billing.mcp_subscription_gate").register()
        logger.info("MCP subscription gate registered")
    except Exception:
        logger.critical(
            "SaaS Phase 8.7 [mcp_subscription_gate] failed — aborting boot "
            "(SEC-9131 fail-loud): /mcp billing enforcement must never be silently absent."
        )
        raise
