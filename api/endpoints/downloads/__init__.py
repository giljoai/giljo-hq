# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Download API endpoints for Giljo HQ
Provides ZIP downloads for slash commands and agent templates.

Token-efficient approach: Instead of writing 15K+ tokens of files,
agents download ZIP files via HTTP (~500 tokens).

Handover 0094: Token-Efficient MCP Downloads

TSK-9209 / IMP-9169 §3.1: this package is the behavior-preserving split of the
former single-file api/endpoints/downloads.py (1005 lines). Route groups live in
submodules; this ``__init__`` owns the aggregate ``router`` (built by including
each submodule's sub-router in the original source order) and re-exports every
symbol other modules and tests reach via ``api.endpoints.downloads.<symbol>``:

- bundles.py: slash-command / agent-template ZIPs, install scripts, bootstrap prompt
- tokens.py:  one-time download-token generation + token-authenticated temp download
- logs.py:    CE-only log downloads on the dedicated ``log_router``

``log_router`` is deliberately NOT included in the aggregate ``router``. It stays a
separate exported router because ``register_routers`` includes it at CALL time only
in CE (TSK-9125) -- folding it into ``router`` would expose CE-only log routes in
SaaS.
"""

from fastapi import APIRouter

from . import bundles, logs, tokens
from .bundles import (
    create_zip_archive,
    download_agent_templates,
    download_install_script,
    download_slash_commands,
    get_bootstrap_prompt,
    render_install_script,
)
from .logs import (
    _ARCHIVE_PATTERN,
    _LOG_DIR,
    download_current_log,
    download_log_archive,
    list_log_archives,
    log_router,
)
from .tokens import (
    download_temp_file,
    generate_download_token,
)


router = APIRouter()
# Include sub-routers in the original source order (bundles → tokens). Order is
# preserved for parity; no overlapping (path, method) pairs exist across groups,
# so matching is unaffected. Each submodule router carries the /api/download
# prefix itself, exactly as the former single-file module's router did.
router.include_router(bundles.router)
router.include_router(tokens.router)


__all__ = [
    "_ARCHIVE_PATTERN",
    "_LOG_DIR",
    "bundles",
    "create_zip_archive",
    "download_agent_templates",
    "download_current_log",
    "download_install_script",
    "download_log_archive",
    "download_slash_commands",
    "download_temp_file",
    "generate_download_token",
    "get_bootstrap_prompt",
    "list_log_archives",
    "log_router",
    "logs",
    "render_install_script",
    "router",
    "tokens",
]
