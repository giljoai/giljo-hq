# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from pathlib import Path

import pytest

from giljo_mcp import database as db_module
from giljo_mcp.config_manager import ConfigManager, DatabaseConfig
from giljo_mcp.database import DEFAULT_MAX_OVERFLOW, DEFAULT_POOL_SIZE, DatabaseManager


FAKE_URL = "postgresql://u:p@localhost:5432/giljo_inf3009a_fake"


def _pool(manager: DatabaseManager):
    return manager.async_engine.sync_engine.pool


class TestPsutilGoneFromPoolPath:

    def test_auto_pool_size_method_removed(self):
        assert not hasattr(DatabaseManager, "_auto_pool_size"), "_auto_pool_size must be deleted"

    def test_database_module_does_not_import_psutil(self):
        source = Path(db_module.__file__).read_text(encoding="utf-8")
        assert "import psutil" not in source, "database.py pool path must not import psutil"
        assert "psutil." not in source, "database.py must not call into psutil"


class TestFixedPoolDefaultsNotRamDerived:

    def test_default_pool_is_fixed_constant(self):
        mgr = DatabaseManager(FAKE_URL, is_async=True)
        assert mgr.pool_size == DEFAULT_POOL_SIZE == 5
        assert mgr.max_overflow == DEFAULT_MAX_OVERFLOW == 5

    def test_huge_fake_ram_has_no_effect_on_pool(self, monkeypatch):
        import psutil

        class _FakeVM:
            total = 256 * (1024**3)

        def _fake_virtual_memory():
            return _FakeVM()

        monkeypatch.setattr(psutil, "virtual_memory", _fake_virtual_memory)

        mgr = DatabaseManager(FAKE_URL, is_async=True)
        assert mgr.pool_size == 5
        assert mgr.max_overflow == 5


class TestExplicitConfigHonored:

    def test_explicit_values_stored_and_on_engine(self):
        mgr = DatabaseManager(FAKE_URL, is_async=True, pool_size=7, max_overflow=3)
        assert mgr.pool_size == 7
        assert mgr.max_overflow == 3
        assert _pool(mgr).size() == 7

    def test_happy_path_default_boot_builds_working_engine(self):
        mgr = DatabaseManager(FAKE_URL, is_async=True)
        assert mgr.async_engine is not None
        assert mgr.AsyncSessionLocal is not None
        assert _pool(mgr).size() == 5


class TestConfigKnobIsAuthoritative:

    def test_new_config_fields_exist_with_defaults(self):
        cfg = DatabaseConfig()
        assert cfg.pg_pool_size == 5
        assert cfg.pg_max_overflow == 5
        assert cfg.pg_slot_budget == 90

    def test_env_overrides_pool_knobs(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.setenv("GILJO_PG_POOL_SIZE", "15")
        monkeypatch.setenv("GILJO_PG_MAX_OVERFLOW", "5")
        monkeypatch.setenv("GILJO_DB_SLOT_BUDGET", "120")

        cfg = ConfigManager(auto_reload=False)
        assert cfg.database.pg_pool_size == 15
        assert cfg.database.pg_max_overflow == 5
        assert cfg.database.pg_slot_budget == 120

    def test_bad_env_value_keeps_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.setenv("GILJO_PG_POOL_SIZE", "not-an-int")

        cfg = ConfigManager(config_path=tmp_path / "nonexistent.yaml", auto_reload=False)
        assert cfg.database.pg_pool_size == 5

    def test_create_database_manager_passes_config_pool(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.setenv("GILJO_DATABASE_URL", FAKE_URL)
        monkeypatch.setenv("GILJO_PG_POOL_SIZE", "12")
        monkeypatch.setenv("GILJO_PG_MAX_OVERFLOW", "4")

        cfg = ConfigManager(auto_reload=False)
        mgr = cfg.create_database_manager()
        assert mgr.pool_size == 12
        assert mgr.max_overflow == 4
        assert _pool(mgr).size() == 12


class TestConnectionBudgetCheck:

    def test_over_budget_warns_and_does_not_raise(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=50, max_overflow=50, workers=2, slot_budget=90)

        assert any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_under_budget_no_warning(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=10, max_overflow=10, workers=1, slot_budget=90)

        assert not any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_non_numeric_inputs_raise_naming_the_input(self):
        from api.startup.database import check_connection_budget

        with pytest.raises(ValueError, match="pool_size"):
            check_connection_budget(pool_size=object(), max_overflow=10, workers=1, slot_budget=90)

    def test_worker_count_reads_web_concurrency(self, monkeypatch):
        from api.startup.database import _worker_count

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        assert _worker_count() == 4

        monkeypatch.setenv("WEB_CONCURRENCY", "garbage")
        with pytest.raises(ValueError, match="WEB_CONCURRENCY"):
            _worker_count()

        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        assert _worker_count() == 1
