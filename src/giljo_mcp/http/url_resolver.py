# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os

from fastapi import Request
from starlette.requests import Request as StarletteRequest
from starlette.types import Scope


logger = logging.getLogger(__name__)

MCP_RESOURCE_PATH = "/mcp"

GILJO_PUBLIC_URL_DEFAULT = "http://localhost:7272"

_saas_pin_missing_warned = False


def _saas_pinned_base_url() -> str | None:
    if os.environ.get("GILJO_MODE", "").strip().lower() != "saas":
        return None
    pinned = os.environ.get("GILJO_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not pinned:
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
    return os.environ.get("GILJO_PUBLIC_URL", "").strip().rstrip("/") or GILJO_PUBLIC_URL_DEFAULT


def get_public_base_url(request: Request) -> str:
    pinned = _saas_pinned_base_url()
    if pinned:
        return pinned
    return str(request.base_url).rstrip("/")


def get_canonical_mcp_resource_uri(request: Request) -> str:
    return f"{get_public_base_url(request)}{MCP_RESOURCE_PATH}"


def get_canonical_mcp_resource_uri_from_scope(scope: Scope) -> str:
    pinned = _saas_pinned_base_url()
    if pinned:
        return f"{pinned}{MCP_RESOURCE_PATH}"
    request = StarletteRequest(scope)
    return f"{str(request.base_url).rstrip('/')}{MCP_RESOURCE_PATH}"
