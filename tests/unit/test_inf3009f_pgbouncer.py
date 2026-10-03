# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from giljo_mcp.database import DatabaseManager, _pgbouncer_connect_args


FAKE_URL = "postgresql://u:p@localhost:5432/giljo_inf3009f_fake"

_PGBOUNCER_KEYS = {
    "statement_cache_size",
    "prepared_statement_cache_size",
    "prepared_statement_name_func",
}


def _connect_params(manager: DatabaseManager) -> dict:
    creator = manager.async_engine.sync_engine.pool._creator
    return dict(inspect.getclosurevars(creator).nonlocals["cparams"])


class TestP1HelperContract:

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        assert _pgbouncer_connect_args() is None

    def test_returns_none_for_non_one_values(self, monkeypatch):
        for value in ("0", "true", "yes", "on", ""):
            monkeypatch.setenv("GILJO_PGBOUNCER", value)
            assert _pgbouncer_connect_args() is None, f"{value!r} must be treated as OFF"

    def test_returns_disable_args_when_on(self, monkeypatch):
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        args = _pgbouncer_connect_args()
        assert args is not None
        assert args["statement_cache_size"] == 0
        assert args["prepared_statement_cache_size"] == 0
        assert callable(args["prepared_statement_name_func"])

    def test_name_func_is_unique_per_call(self, monkeypatch):
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        name_func = _pgbouncer_connect_args()["prepared_statement_name_func"]
        names = {name_func() for _ in range(100)}
        assert len(names) == 100, "each prepared-statement name must be unique (uuid)"
        assert all(n.startswith("__asyncpg_") for n in names)


class TestP1EngineOffIsByteIdentical:

    def test_pooled_engine_has_no_pgbouncer_keys(self, monkeypatch):
        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True))
        assert _PGBOUNCER_KEYS.isdisjoint(params), f"unexpected pooling keys: {params}"

    def test_null_pool_engine_has_no_pgbouncer_keys(self, monkeypatch):
        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True, use_null_pool=True))
        assert _PGBOUNCER_KEYS.isdisjoint(params)


class TestP1EngineOnDisablesPreparedStatements:

    def test_pooled_engine_disables_prepared_statements(self, monkeypatch):
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True))
        assert params["statement_cache_size"] == 0
        assert params["prepared_statement_cache_size"] == 0
        assert callable(params["prepared_statement_name_func"])

    def test_null_pool_engine_disables_prepared_statements(self, monkeypatch):
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True, use_null_pool=True))
        assert params["statement_cache_size"] == 0
        assert params["prepared_statement_cache_size"] == 0

    def test_engine_still_builds_and_is_usable_when_on(self, monkeypatch):
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        mgr = DatabaseManager(FAKE_URL, is_async=True)
        assert mgr.async_engine is not None
        assert mgr.AsyncSessionLocal is not None


class TestP2BrokerDsnSeam:

    def _state(self, app_url: str = "postgresql://app:pw@pooler:6432/db") -> SimpleNamespace:
        return SimpleNamespace(db_manager=SimpleNamespace(database_url=app_url))

    def test_falls_back_to_app_url_when_unset(self, monkeypatch):
        from api.startup.core_services import _resolve_broker_dsn

        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        assert _resolve_broker_dsn(self._state()) == "postgresql://app:pw@pooler:6432/db"

    def test_uses_direct_url_when_set(self, monkeypatch):
        from api.startup.core_services import _resolve_broker_dsn

        direct = "postgresql://app:pw@direct:5432/db"
        monkeypatch.setenv("GILJO_BROKER_DATABASE_URL", direct)
        assert _resolve_broker_dsn(self._state()) == direct

    def test_empty_var_falls_back(self, monkeypatch):
        from api.startup.core_services import _resolve_broker_dsn

        monkeypatch.setenv("GILJO_BROKER_DATABASE_URL", "")
        assert _resolve_broker_dsn(self._state()) == "postgresql://app:pw@pooler:6432/db"


class TestPairingAssertion:

    def test_noop_when_flag_off(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        assert_pgbouncer_broker_pairing()

    def test_noop_for_non_one_flag_values(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        for value in ("0", "true", "yes", ""):
            monkeypatch.setenv("GILJO_PGBOUNCER", value)
            assert_pgbouncer_broker_pairing()

    def test_raises_when_flag_on_and_broker_url_missing(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="GILJO_BROKER_DATABASE_URL"):
            assert_pgbouncer_broker_pairing()

    def test_empty_broker_url_counts_as_missing(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        monkeypatch.setenv("GILJO_BROKER_DATABASE_URL", "")
        with pytest.raises(RuntimeError, match="GILJO_BROKER_DATABASE_URL"):
            assert_pgbouncer_broker_pairing()

    def test_passes_when_paired(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        monkeypatch.setenv("GILJO_BROKER_DATABASE_URL", "postgresql://app:pw@direct:5432/db")
        assert_pgbouncer_broker_pairing()

    async def test_single_worker_degrade_cannot_swallow_it(self, monkeypatch):
        from api.startup.core_services import init_websocket_broker

        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        with pytest.raises(RuntimeError, match="GILJO_BROKER_DATABASE_URL"):
            await init_websocket_broker(SimpleNamespace())


class TestConnectionBudgetHonestAccounting:

    def test_prod_shape_now_warns(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=10, max_overflow=10, workers=4, slot_budget=90, broker_per_worker=6)
        assert any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_reserved_slots_counted(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=10, max_overflow=10, workers=1, slot_budget=30, reserved_slots=15)
        assert any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_legacy_call_shape_unchanged(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=10, max_overflow=10, workers=1, slot_budget=90)
        assert not any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_pgbouncer_mode_scores_only_direct_connections(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("INFO"):
            check_connection_budget(
                pool_size=50,
                max_overflow=50,
                workers=4,
                slot_budget=90,
                broker_per_worker=6,
                pgbouncer=True,
            )
        assert not any("budget EXCEEDED" in r.message for r in caplog.records)
        assert any("PgBouncer mode" in r.message for r in caplog.records)

    def test_pgbouncer_mode_still_warns_on_direct_overrun(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(
                pool_size=10,
                max_overflow=10,
                workers=3,
                slot_budget=90,
                broker_per_worker=40,
                pgbouncer=True,
            )
        assert any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_broker_direct_connections_resolves_from_env(self, monkeypatch):
        from api.broker.postgres_notify import MAX_DB_CONNECTIONS_PER_PROCESS
        from api.startup.database import _broker_direct_connections

        monkeypatch.setenv("GILJO_WS_BROKER", "postgres_notify")
        assert _broker_direct_connections(None) == MAX_DB_CONNECTIONS_PER_PROCESS == 6

        monkeypatch.delenv("GILJO_WS_BROKER", raising=False)
        monkeypatch.delenv("GILJO_WEBSOCKET_BROKER", raising=False)
        assert _broker_direct_connections(None) == 0

    def test_reserved_slots_env_parsing(self, monkeypatch):
        from api.startup.database import _reserved_slots

        monkeypatch.delenv("GILJO_DB_RESERVED_SLOTS", raising=False)
        assert _reserved_slots() == 0

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "26")
        assert _reserved_slots() == 26

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "garbage")
        with pytest.raises(ValueError, match="GILJO_DB_RESERVED_SLOTS"):
            _reserved_slots()

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "-5")
        assert _reserved_slots() == 0


class TestP3AlembicHonorsDatabaseUrl:

    def test_resolve_db_url_reads_database_url_first(self):
        path = Path(__file__).resolve().parents[2] / "scripts" / "alembic_cli.py"
        if not path.exists():
            pytest.skip(reason="scripts/alembic_cli.py absent (stripped from the CE export); P3 guard N/A")
        source = path.read_text(encoding="utf-8")
        assert 'os.getenv("DATABASE_URL")' in source, (
            "alembic_cli must resolve DATABASE_URL; the railway preDeploy "
            "DATABASE_URL=$DATABASE_UNPOOLED_URL override (P3) relies on it"
        )
        assert source.index('os.getenv("DATABASE_URL")') < source.index('os.getenv("POSTGRES_HOST"')
