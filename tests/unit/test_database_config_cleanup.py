# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect

from giljo_mcp.config_manager import DatabaseConfig, get_config


class TestDatabaseConfigCleanup:

    def test_new_fields_exist(self):
        db = DatabaseConfig()

        assert hasattr(db, "type"), "Missing 'type' field"
        assert hasattr(db, "host"), "Missing 'host' field"
        assert hasattr(db, "port"), "Missing 'port' field"
        assert hasattr(db, "database_name"), "Missing 'database_name' field"
        assert hasattr(db, "username"), "Missing 'username' field"
        assert hasattr(db, "password"), "Missing 'password' field"

    def test_legacy_aliases_removed(self):
        db_class = DatabaseConfig
        props = {name for name, obj in inspect.getmembers(db_class) if isinstance(obj, property)}

        assert "database_type" not in props, "Legacy alias 'database_type' still exists"
        assert "pg_host" not in props, "Legacy alias 'pg_host' still exists"
        assert "pg_port" not in props, "Legacy alias 'pg_port' still exists"
        assert "pg_database" not in props, "Legacy alias 'pg_database' still exists"
        assert "pg_user" not in props, "Legacy alias 'pg_user' still exists"
        assert "pg_password" not in props, "Legacy alias 'pg_password' still exists"

    def test_new_fields_work(self):
        db = DatabaseConfig()

        db.type = "postgresql"
        db.host = "testhost"
        db.port = 5433
        db.database_name = "testdb"
        db.username = "testuser"
        db.password = "testpass"

        assert db.type == "postgresql"
        assert db.host == "testhost"
        assert db.port == 5433
        assert db.database_name == "testdb"
        assert db.username == "testuser"
        assert db.password == "testpass"

    def test_defaults(self):
        db = DatabaseConfig()

        assert db.type == "postgresql"
        assert db.host == "localhost"
        assert db.port == 5432
        assert db.username == "postgres"
        assert db.password == ""
        assert db.database_name == "giljo_mcp.db"

    def test_config_loads(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test")

        config = get_config()
        assert config is not None
        assert hasattr(config, "database")
        assert isinstance(config.database, DatabaseConfig)

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "envhost")
        monkeypatch.setenv("DB_PORT", "5434")
        monkeypatch.setenv("DB_NAME", "envdb")
        monkeypatch.setenv("DB_USER", "envuser")
        monkeypatch.setenv("DB_PASSWORD", "envpass")

        from giljo_mcp.config_manager import ConfigManager

        config = ConfigManager()

        assert config.database.host == "envhost"
        assert config.database.port == 5434
        assert config.database.database_name == "envdb"
        assert config.database.username == "envuser"
        assert config.database.password == "envpass"
