# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import threading
import time
from pathlib import Path
from typing import Any

from giljo_mcp._config_io import read_config


logger = logging.getLogger(__name__)


class ConfigService:

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path.cwd() / "config.yaml"
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 60
        self._last_read: float | None = None
        self._lock = threading.RLock()

    def get_serena_config(self, use_cache: bool = True) -> dict[str, Any]:
        if use_cache and self._is_cache_valid():
            return self._cache.get("serena_mcp", {})

        config = self._read_config()
        serena_config = config.get("features", {}).get("serena_mcp", {})

        with self._lock:
            self._cache["serena_mcp"] = serena_config
            self._last_read = time.time()

        return serena_config

    def _is_cache_valid(self) -> bool:
        if not self._last_read:
            return False
        return (time.time() - self._last_read) < self._cache_ttl

    def _read_config(self) -> dict[str, Any]:
        return read_config(self.config_path)

    def invalidate_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._last_read = None
