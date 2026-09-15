# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import yaml

import giljo_mcp.config_manager as cm
from giljo_mcp.config_manager import ConfigManager


class TestTenantManagerFlagsRemoved:
    def test_config_manager_has_no_get_tenant_manager(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        assert not hasattr(ConfigManager(), "get_tenant_manager")

    def test_featureflags_dataclass_removed(self):
        assert not hasattr(cm, "FeatureFlags")

    def test_config_has_no_features_attr(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        assert not hasattr(ConfigManager(), "features")

    def test_get_all_settings_has_no_features_key(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        settings = ConfigManager().get_all_settings()
        assert "features" not in settings

    def test_env_vars_are_inert(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        monkeypatch.setenv("ENABLE_MULTI_TENANT", "false")
        monkeypatch.setenv("ENABLE_WEBSOCKET", "false")

        config = ConfigManager()

        assert not hasattr(config, "features")

    def test_legacy_features_block_in_config_is_tolerated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PASSWORD", "test")
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "features": {
                        "multi_tenant": True,
                        "websocket_updates": True,
                    }
                }
            )
        )

        config = ConfigManager(config_path=config_file, auto_reload=False)

        assert not hasattr(config, "features")
