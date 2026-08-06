# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SaaS enforcement-wiring boot gate — Phases 8.6 / 8.7 (SEC-9131, fail-loud).

Extracted from ``api/app.py``'s lifespan so the fail-loud policy is unit-testable
(mirrors INF-3009c's extraction of Phase 8.5 into ``cache_backends_gate.py``).

Policy: in SaaS mode a failure to register the tenant-scope widening (Phase 8.6)
or the /mcp subscription gate (Phase 8.7) ABORTS boot — the exception propagates
out of ``lifespan()`` and stops uvicorn, exactly like the Phase 0 license check
and Phase 8.5 Redis gate. Silently degrading would ship prod with enforcement
absent while looking healthy (BE-6069 incident class).

Both functions are pure no-ops for CE (``giljo_mode != "saas"``) and reach the
``saas/`` tree only through ``importlib`` — no static SaaS import crosses the
boundary, so the Deletion Test holds.
"""

from __future__ import annotations

import importlib
import logging
import os
from urllib.parse import urlsplit


logger = logging.getLogger("api.app")


def register_saas_tenant_scoped_models(*, giljo_mode: str) -> None:
    """Phase 8.6 — register SaaS-only tenant-scoped models (BE-6037). Fail-loud."""
    if giljo_mode != "saas":
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
    """Phase 8.58 — SaaS origin-pin presence gate (SEC-9227h / M7). Fail-loud.

    The SaaS origin pin (SEC-9171 #30) only activates when BOTH
    ``GILJO_MODE=saas`` AND ``GILJO_PUBLIC_BASE_URL`` are set. Without this
    gate a SaaS boot with the var unset succeeds silently and the OAuth
    issuer, every advertised endpoint URL, the JWT ``aud`` claim, and emailed
    lifecycle links all derive from the attacker-influenceable Host /
    X-Forwarded-Host header (uvicorn ``proxy_headers=True``) — cache-poisonable
    behind CDNs. A malformed pin is as bad as a missing one, so the value is
    validated too. CE/LAN request-derived resolution is deliberate and this
    gate never runs there.
    """
    if giljo_mode != "saas":
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
    """Return a human-readable defect in the pin value, or None if valid.

    Valid: an https:// origin with a hostname, no credentials, and no
    path/query/fragment beyond an optional trailing slash. http:// is allowed
    ONLY for localhost — local SaaS-mode dev runs without TLS.
    """
    try:
        parts = urlsplit(pinned)
        hostname = parts.hostname  # lazy property — can raise on malformed netloc
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
    """Phase 8.7 — register the /mcp subscription gate (BE-6060d). Fail-loud."""
    if giljo_mode != "saas":
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
