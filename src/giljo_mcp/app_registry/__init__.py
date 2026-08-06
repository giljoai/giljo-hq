# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Application service registry for Giljo HQ.

Provides module-level holders for singletons that are created at startup
and needed by lower-layer code that cannot import from api/.

Set by api/app.py (or startup hooks); consumed by src/giljo_mcp/ code.
"""

from giljo_mcp.app_registry.service_registry import get_websocket_manager, set_websocket_manager


__all__ = [
    "get_websocket_manager",
    "set_websocket_manager",
]
