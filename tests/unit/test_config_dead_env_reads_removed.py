# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp.config_manager import ConfigManager, ServerConfig


class TestDeadEnvReadsRemoved:
    def test_server_config_has_no_debug_field(self):
        assert not hasattr(ServerConfig(), "debug")

    def test_giljo_debug_env_var_is_inert(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        monkeypatch.setenv("GILJO_DEBUG", "true")

        config = ConfigManager()

        assert not hasattr(config.server, "debug")

    def test_get_all_settings_has_no_debug_key(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")

        config = ConfigManager()
        settings = config.get_all_settings()

        assert "debug" not in settings["server"]

    def test_giljo_database_type_env_var_is_inert(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        monkeypatch.delenv("DB_TYPE", raising=False)
        monkeypatch.setenv("GILJO_DATABASE_TYPE", "sqlite")

        config = ConfigManager()

        assert config.database.type == "postgresql"

    def test_db_type_env_var_still_live(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")
        monkeypatch.setenv("DB_TYPE", "postgresql")

        config = ConfigManager()

        assert config.database.type == "postgresql"
