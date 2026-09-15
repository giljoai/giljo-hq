# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from fastapi import APIRouter

from . import bundles, logs, tokens
from .bundles import (
    create_zip_archive,
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
router.include_router(bundles.router)
router.include_router(tokens.router)


__all__ = [
    "_ARCHIVE_PATTERN",
    "_LOG_DIR",
    "bundles",
    "create_zip_archive",
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
