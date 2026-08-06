# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Configuration service for centralized config.yaml management.

Updated Handover 0731: Reviewed for typed returns - dict[str, Any] retained because
config values are read from YAML files with dynamic, deployment-specific schemas.

Runtime settings (git, serena, SSL, cookie domains) now live in the database
(Settings table) and should be read via SettingsService. The sync
get_serena_config() method remains as a fallback for synchronous callers that
cannot use async DB access.

BE-9360: that fallback's only production caller was ``template_manager``, which
has been deleted, so ``get_serena_config()`` is now exercised solely by
``tests/unit/test_config_service.py``. It is left in place deliberately -- BE-9360
was scoped to the template-manager cluster and this is a separate module, so the
observation is recorded here rather than acted on.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any

from giljo_mcp._config_io import read_config


logger = logging.getLogger(__name__)


class ConfigService:
    """
    Centralized configuration management service.

    Provides thread-safe access to config.yaml with caching
    and automatic template cache invalidation.

    For runtime settings (integrations, security), prefer SettingsService
    which reads from the database. This class remains for sync callers
    and infrastructure config that stays in config.yaml.
    """

    def __init__(self, config_path: Path | None = None):
        """
        Initialize ConfigService.

        Args:
            config_path: Path to config.yaml (defaults to cwd/config.yaml)
        """
        self.config_path = config_path or Path.cwd() / "config.yaml"
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 60  # seconds
        self._last_read: float | None = None
        self._lock = threading.RLock()

    def get_serena_config(self, use_cache: bool = True) -> dict[str, Any]:
        """
        Get Serena configuration from config.yaml (sync fallback).

        For async callers with DB access, use SettingsService instead:
            service = SettingsService(session, tenant_key)
            integrations = await service.get_settings("integrations")
            serena = integrations.get("serena_mcp", {})

        Args:
            use_cache: Whether to use cached config

        Returns:
            dict[str, Any] - Serena config with keys: enabled, installed, registered.
            Intentionally returns dict because YAML config structure varies by
            deployment and feature flags (not a fixed schema).
        """
        if use_cache and self._is_cache_valid():
            return self._cache.get("serena_mcp", {})

        config = self._read_config()
        serena_config = config.get("features", {}).get("serena_mcp", {})

        with self._lock:
            self._cache["serena_mcp"] = serena_config
            self._last_read = time.time()

        return serena_config

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._last_read:
            return False
        return (time.time() - self._last_read) < self._cache_ttl

    def _read_config(self) -> dict[str, Any]:
        """Read config.yaml. Returns raw YAML data as dict (dynamic structure)."""
        return read_config(self.config_path)

    def invalidate_cache(self) -> None:
        """Force cache refresh on next read."""
        with self._lock:
            self._cache.clear()
            self._last_read = None
