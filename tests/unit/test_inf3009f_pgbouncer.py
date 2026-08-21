# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-3009f — PgBouncer transaction-pooling prerequisites (config-gated, default OFF).

Regression tests at the failing layer:
- P1: ``_create_async_engine`` prepared-statement disable, proven on the LIVE engine's
  merged asyncpg connect params (the layer ``DuplicatePreparedStatementError`` would
  fire at). Default OFF must be byte-identical (no connect_args at all).
- P2: the broker-DSN seam in ``init_websocket_broker`` — the broker must be able to
  take a DIRECT (unpooled) DSN so its session-pinned LISTEN survives, with a fallback
  to the app URL that is byte-identical when the var is unset.
- P3: a source guard that ``scripts/alembic_cli.py`` still resolves ``DATABASE_URL``
  first, which the railway preDeploy ``DATABASE_URL=$DATABASE_UNPOOLED_URL`` override
  relies on.
- Deployment prep (this lane): the boot-time two-variable pairing assertion
  (``GILJO_PGBOUNCER=1`` requires ``GILJO_BROKER_DATABASE_URL``), proven at the layer
  that could swallow it (``init_websocket_broker``'s single-worker degrade), and the
  honest connection-budget accounting (broker + reserved + PgBouncer-aware).

These tests touch NO database — SQLAlchemy engines are lazy (no connection until first
checkout), so constructing a DatabaseManager with a fake URL is safe and parallel-safe.
Env state is isolated via monkeypatch (no module-level mutable state, no ordering deps).
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from giljo_mcp.database import DatabaseManager, _pgbouncer_connect_args


FAKE_URL = "postgresql://u:p@localhost:5432/giljo_inf3009f_fake"

# The three asyncpg keys P1 injects to make prepared statements pooling-safe.
_PGBOUNCER_KEYS = {
    "statement_cache_size",
    "prepared_statement_cache_size",
    "prepared_statement_name_func",
}


def _connect_params(manager: DatabaseManager) -> dict:
    """Return the FINAL merged asyncpg connect params off the live engine.

    SQLAlchemy folds user ``connect_args`` into the pool creator's closure
    (``cparams``) together with the host/user/db parsed from the URL, and that dict is
    exactly what is handed to ``asyncpg.connect`` at checkout — so it is the real proof
    of what the driver will do, not a mock of our own call.
    """
    creator = manager.async_engine.sync_engine.pool._creator
    return dict(inspect.getclosurevars(creator).nonlocals["cparams"])


class TestP1HelperContract:
    """The env gate itself: only ``GILJO_PGBOUNCER=1`` turns it on."""

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        assert _pgbouncer_connect_args() is None

    def test_returns_none_for_non_one_values(self, monkeypatch):
        # Matches the GILJO_FORCE_HTTP == "1" idiom: anything but "1" is OFF.
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
    """DoD: flag OFF adds NO connect_args — behavior byte-identical to pre-INF-3009f."""

    def test_pooled_engine_has_no_pgbouncer_keys(self, monkeypatch):
        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True))
        assert _PGBOUNCER_KEYS.isdisjoint(params), f"unexpected pooling keys: {params}"

    def test_null_pool_engine_has_no_pgbouncer_keys(self, monkeypatch):
        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True, use_null_pool=True))
        assert _PGBOUNCER_KEYS.isdisjoint(params)


class TestP1EngineOnDisablesPreparedStatements:
    """DoD (fix works): flag ON puts statement_cache_size==0 on the live engine params."""

    def test_pooled_engine_disables_prepared_statements(self, monkeypatch):
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True))
        assert params["statement_cache_size"] == 0
        assert params["prepared_statement_cache_size"] == 0
        assert callable(params["prepared_statement_name_func"])

    def test_null_pool_engine_disables_prepared_statements(self, monkeypatch):
        """The test-harness NullPool async branch must gate too (correct behind a pooler)."""
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        params = _connect_params(DatabaseManager(FAKE_URL, is_async=True, use_null_pool=True))
        assert params["statement_cache_size"] == 0
        assert params["prepared_statement_cache_size"] == 0

    def test_engine_still_builds_and_is_usable_when_on(self, monkeypatch):
        """Two-sided: turning the flag on still yields a working async engine (no crash)."""
        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        mgr = DatabaseManager(FAKE_URL, is_async=True)
        assert mgr.async_engine is not None
        assert mgr.AsyncSessionLocal is not None


class TestP2BrokerDsnSeam:
    """DoD: the broker can take a DIRECT DSN; unset falls back byte-identically."""

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
        # Even though the app URL points at the pooler, the broker gets the direct URL.
        assert _resolve_broker_dsn(self._state()) == direct

    def test_empty_var_falls_back(self, monkeypatch):
        from api.startup.core_services import _resolve_broker_dsn

        monkeypatch.setenv("GILJO_BROKER_DATABASE_URL", "")
        assert _resolve_broker_dsn(self._state()) == "postgresql://app:pw@pooler:6432/db"


class TestPairingAssertion:
    """The two-variable pairing is enforced structurally, not by prose (INF-3009f prep).

    GILJO_PGBOUNCER=1 without GILJO_BROKER_DATABASE_URL means the broker's
    session-pinned LISTEN would run through transaction pooling and die silently
    (cross-worker realtime + live-session revocation). Boot must refuse instead.
    """

    def test_noop_when_flag_off(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.delenv("GILJO_PGBOUNCER", raising=False)
        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        assert_pgbouncer_broker_pairing()  # must not raise

    def test_noop_for_non_one_flag_values(self, monkeypatch):
        from api.startup.core_services import assert_pgbouncer_broker_pairing

        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        for value in ("0", "true", "yes", ""):
            monkeypatch.setenv("GILJO_PGBOUNCER", value)
            assert_pgbouncer_broker_pairing()  # anything but "1" is OFF

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
        assert_pgbouncer_broker_pairing()  # must not raise

    async def test_single_worker_degrade_cannot_swallow_it(self, monkeypatch):
        """Regression at the failing layer: init_websocket_broker's single-worker
        degrade path swallows broker exceptions — the pairing assertion must abort
        boot BEFORE that try block, at ANY worker count."""
        from api.startup.core_services import init_websocket_broker

        monkeypatch.setenv("GILJO_PGBOUNCER", "1")
        monkeypatch.delenv("GILJO_BROKER_DATABASE_URL", raising=False)
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        # A bare state object: the assertion must fire before anything touches it.
        with pytest.raises(RuntimeError, match="GILJO_BROKER_DATABASE_URL"):
            await init_websocket_broker(SimpleNamespace())


class TestConnectionBudgetHonestAccounting:
    """The budget check counts the broker + declared external services and is
    PgBouncer-aware — the green 'budget OK' line must stop lying (INF-3009f prep)."""

    def test_prod_shape_now_warns(self, caplog):
        """e.g. 4 workers x (10+10 pool + 6 broker) = 104 > 90: a multi-worker shape
        the old math scored as 80 <= 90 'OK'."""
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=10, max_overflow=10, workers=4, slot_budget=90, broker_per_worker=6)
        assert any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_reserved_slots_counted(self, caplog):
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            # 1 x (10+10+0) + 15 reserved = 35 > 30
            check_connection_budget(pool_size=10, max_overflow=10, workers=1, slot_budget=30, reserved_slots=15)
        assert any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_legacy_call_shape_unchanged(self, caplog):
        """The 4-arg call (defaults: broker 0, reserved 0, no pgbouncer) keeps the
        INF-3009a arithmetic byte-identical."""
        from api.startup.database import check_connection_budget

        with caplog.at_level("WARNING"):
            check_connection_budget(pool_size=10, max_overflow=10, workers=1, slot_budget=90)
        assert not any("budget EXCEEDED" in r.message for r in caplog.records)

    def test_pgbouncer_mode_scores_only_direct_connections(self, caplog):
        """Behind PgBouncer the SQLAlchemy pool terminates at the pooler: a pool that
        would blow the budget direct (4 x 100 = 400) must NOT warn when only the
        direct connections (4 x 6 = 24) face Postgres."""
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
            # direct: 3 x 40 = 120 > 90 — even pooled setups can overrun via direct conns
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
        assert _broker_direct_connections(None) == 0  # in_memory default holds no DB conns

    def test_reserved_slots_env_parsing(self, monkeypatch):
        from api.startup.database import _reserved_slots

        monkeypatch.delenv("GILJO_DB_RESERVED_SLOTS", raising=False)
        assert _reserved_slots() == 0

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "26")
        assert _reserved_slots() == 26

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "garbage")
        assert _reserved_slots() == 0

        monkeypatch.setenv("GILJO_DB_RESERVED_SLOTS", "-5")
        assert _reserved_slots() == 0


class TestP3AlembicHonorsDatabaseUrl:
    """P3 guard: the railway preDeploy DATABASE_URL override depends on this precedence.

    A source scan (not an import) because ``scripts/alembic_cli.py`` runs os.chdir and
    patches alembic's CommandLine at module import — importing it in a pytest-xdist
    worker would not be parallel-safe. The guard still fails loudly if a refactor drops
    the DATABASE_URL-first resolution the override relies on.
    """

    def test_resolve_db_url_reads_database_url_first(self):
        path = Path(__file__).resolve().parents[2] / "scripts" / "alembic_cli.py"
        if not path.exists():
            # scripts/alembic_cli.py is SaaS/operator tooling; export_ce.sh strips it
            # from the public CE tree (only 4 scripts/ files ship). The P3 direct-URL
            # guard applies only where that deploy tooling exists, so it is N/A here.
            pytest.skip(reason="scripts/alembic_cli.py absent (stripped from the CE export); P3 guard N/A")
        source = path.read_text(encoding="utf-8")
        assert 'os.getenv("DATABASE_URL")' in source, (
            "alembic_cli must resolve DATABASE_URL; the railway preDeploy "
            "DATABASE_URL=$DATABASE_UNPOOLED_URL override (P3) relies on it"
        )
        # DATABASE_URL must be consulted before the POSTGRES_* fallback parts, so the
        # override wins over any ambient POSTGRES_HOST/PORT.
        assert source.index('os.getenv("DATABASE_URL")') < source.index('os.getenv("POSTGRES_HOST"')
