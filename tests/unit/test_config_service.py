# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from giljo_mcp.services.config_service import ConfigService


class TestConfigService:

    def test_init_default_path(self):
        service = ConfigService()
        assert service.config_path == Path.cwd() / "config.yaml"
        assert service._cache == {}
        assert service._last_read is None

    def test_init_custom_path(self):
        custom_path = Path("/custom/config.yaml")
        service = ConfigService(config_path=custom_path)
        assert service.config_path == custom_path

    def test_get_serena_config_file_not_found(self, tmp_path):
        config_path = tmp_path / "nonexistent.yaml"
        service = ConfigService(config_path=config_path)

        result = service.get_serena_config()

        assert result == {}

    def test_get_serena_config_empty_features(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("installation:\n  mode: localhost\n")

        service = ConfigService(config_path=config_path)
        result = service.get_serena_config()

        assert result == {}

    def test_get_serena_config_success(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: true
    installed: true
    registered: true
"""
        )

        service = ConfigService(config_path=config_path)
        result = service.get_serena_config()

        assert result["enabled"] is True
        assert result["installed"] is True
        assert result["registered"] is True

    def test_get_serena_config_disabled(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: false
    installed: false
"""
        )

        service = ConfigService(config_path=config_path)
        result = service.get_serena_config()

        assert result["enabled"] is False
        assert result["installed"] is False

    def test_cache_is_used(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: true
"""
        )

        service = ConfigService(config_path=config_path)

        result1 = service.get_serena_config()
        assert result1["enabled"] is True

        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: false
"""
        )

        result2 = service.get_serena_config(use_cache=True)
        assert result2["enabled"] is True

        result3 = service.get_serena_config(use_cache=False)
        assert result3["enabled"] is False

    def test_cache_expiration(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: true
"""
        )

        service = ConfigService(config_path=config_path)
        service._cache_ttl = 0.1

        result1 = service.get_serena_config()
        assert result1["enabled"] is True

        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: false
"""
        )

        time.sleep(0.2)

        result2 = service.get_serena_config()
        assert result2["enabled"] is False

    def test_invalidate_cache(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: true
"""
        )

        service = ConfigService(config_path=config_path)

        result1 = service.get_serena_config()
        assert result1["enabled"] is True

        service.invalidate_cache()
        assert service._cache == {}
        assert service._last_read is None

        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: false
"""
        )

        result2 = service.get_serena_config()
        assert result2["enabled"] is False

    def test_malformed_yaml_handling(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{ invalid yaml: [")

        service = ConfigService(config_path=config_path)
        result = service.get_serena_config()

        assert result == {}

    def test_thread_safety(self, tmp_path):
        import threading

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
features:
  serena_mcp:
    enabled: true
"""
        )

        service = ConfigService(config_path=config_path)
        results = []

        def read_config():
            result = service.get_serena_config()
            results.append(result)

        threads = [threading.Thread(target=read_config) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(results) == 10
        assert all(r.get("enabled") is True for r in results)
