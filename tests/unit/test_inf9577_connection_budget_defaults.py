# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from pathlib import Path

import pytest

from api.broker.postgres_notify import MAX_DB_CONNECTIONS_PER_PROCESS
from api.startup.database import _broker_direct_connections, check_connection_budget
from giljo_mcp.config_manager import DatabaseConfig


REPO_ROOT = Path(__file__).resolve().parents[2]

REFERENCE_WEB_WORKERS = 4
REFERENCE_WORKER_SERVICE_PROCESSES = 1

REFERENCE_WEB_INSTANCES = 1
REFERENCE_WORKER_SERVICE_INSTANCES = 1

REFERENCE_POOL_OPENING_PROCESSES = (
    REFERENCE_WEB_WORKERS * REFERENCE_WEB_INSTANCES
    + REFERENCE_WORKER_SERVICE_PROCESSES * REFERENCE_WORKER_SERVICE_INSTANCES
)

REFERENCE_MAX_CONNECTIONS = 100
SUPERUSER_RESERVED_CONNECTIONS = 3
USABLE_SLOTS = REFERENCE_MAX_CONNECTIONS - SUPERUSER_RESERVED_CONNECTIONS

OPERATIONAL_HEADROOM_SLOTS = 8

CE_MIN_CONCURRENT_SESSIONS = 8


def _per_process_worst_case(cfg: DatabaseConfig, broker: int) -> int:
    return cfg.pg_pool_size + cfg.pg_max_overflow + broker


class TestShippedDefaultsFitTheCeiling:

    def test_deployment_wide_worst_case_is_within_the_shipped_slot_budget(self):
        cfg = DatabaseConfig()
        per_process = _per_process_worst_case(cfg, MAX_DB_CONNECTIONS_PER_PROCESS)
        worst_case = REFERENCE_POOL_OPENING_PROCESSES * per_process

        assert worst_case <= cfg.pg_slot_budget, (
            f"Shipped defaults overrun the shipped budget: {REFERENCE_POOL_OPENING_PROCESSES} "
            f"pool-opening process(es) x (pool {cfg.pg_pool_size} + overflow "
            f"{cfg.pg_max_overflow} + broker {MAX_DB_CONNECTIONS_PER_PROCESS}) = "
            f"{worst_case} > budget {cfg.pg_slot_budget}. Lower the per-process pool "
            f"defaults; do not raise the budget to hide it."
        )

    def test_deployment_wide_worst_case_fits_the_measured_postgres_ceiling(self):
        cfg = DatabaseConfig()
        per_process = _per_process_worst_case(cfg, MAX_DB_CONNECTIONS_PER_PROCESS)
        worst_case = REFERENCE_POOL_OPENING_PROCESSES * per_process

        assert worst_case + OPERATIONAL_HEADROOM_SLOTS <= USABLE_SLOTS, (
            f"Shipped defaults overrun the measured server ceiling: {worst_case} "
            f"connections + {OPERATIONAL_HEADROOM_SLOTS} operational = "
            f"{worst_case + OPERATIONAL_HEADROOM_SLOTS} > {USABLE_SLOTS} usable "
            f"({REFERENCE_MAX_CONNECTIONS} max_connections - "
            f"{SUPERUSER_RESERVED_CONNECTIONS} superuser-reserved)."
        )

    def test_the_slot_budget_itself_is_not_a_promise_postgres_cannot_keep(self):
        cfg = DatabaseConfig()
        assert cfg.pg_slot_budget <= USABLE_SLOTS, (
            f"pg_slot_budget {cfg.pg_slot_budget} exceeds the {USABLE_SLOTS} slots the "
            f"server actually has available; the budget would authorise an outage."
        )


class TestTheRuntimeCheckAgreesAtTheRealPosture:

    def test_web_service_boot_reports_budget_ok_with_shipped_defaults(self, caplog):
        cfg = DatabaseConfig()

        with caplog.at_level("WARNING"):
            check_connection_budget(
                pool_size=cfg.pg_pool_size,
                max_overflow=cfg.pg_max_overflow,
                workers=REFERENCE_WEB_WORKERS,
                slot_budget=cfg.pg_slot_budget,
                broker_per_worker=MAX_DB_CONNECTIONS_PER_PROCESS,
                reserved_slots=0,
            )

        exceeded = [r.message for r in caplog.records if "budget EXCEEDED" in r.message]
        assert not exceeded, f"Reference web posture still trips the boot check: {exceeded}"

    def test_worker_service_boot_reports_budget_ok_with_shipped_defaults(self, caplog):
        cfg = DatabaseConfig()

        with caplog.at_level("WARNING"):
            check_connection_budget(
                pool_size=cfg.pg_pool_size,
                max_overflow=cfg.pg_max_overflow,
                workers=REFERENCE_WORKER_SERVICE_PROCESSES,
                slot_budget=cfg.pg_slot_budget,
                broker_per_worker=MAX_DB_CONNECTIONS_PER_PROCESS,
                reserved_slots=0,
            )

        exceeded = [r.message for r in caplog.records if "budget EXCEEDED" in r.message]
        assert not exceeded, f"Reference worker posture still trips the boot check: {exceeded}"

    def test_the_check_still_fires_on_the_defaults_that_shipped_broken(self, caplog):
        with caplog.at_level("WARNING"):
            check_connection_budget(
                pool_size=10,
                max_overflow=10,
                workers=REFERENCE_WEB_WORKERS,
                slot_budget=90,
                broker_per_worker=MAX_DB_CONNECTIONS_PER_PROCESS,
                reserved_slots=0,
            )

        messages = [r.message for r in caplog.records]
        assert any("budget EXCEEDED" in m for m in messages), messages
        assert any("= 104 connections > budget 90" in m for m in messages), messages


class TestCommunityEditionIsNotStarved:

    def test_ce_default_broker_costs_no_database_connections(self, monkeypatch):
        monkeypatch.delenv("GILJO_WS_BROKER", raising=False)
        monkeypatch.delenv("GILJO_WEBSOCKET_BROKER", raising=False)

        assert _broker_direct_connections(None) == 0

    def test_ce_single_worker_pool_does_not_serialise(self):
        cfg = DatabaseConfig()
        ce_concurrent = cfg.pg_pool_size + cfg.pg_max_overflow

        assert ce_concurrent >= CE_MIN_CONCURRENT_SESSIONS, (
            f"CE would run on {ce_concurrent} concurrent DB sessions, below the "
            f"{CE_MIN_CONCURRENT_SESSIONS} floor a single-user dashboard needs before "
            f"ordinary traffic queues on pool_timeout."
        )

    def test_ce_single_worker_fits_a_stock_postgres_with_room_to_spare(self):
        cfg = DatabaseConfig()
        ce_total = cfg.pg_pool_size + cfg.pg_max_overflow

        assert ce_total <= USABLE_SLOTS // 4, (
            f"CE's {ce_total} connections are a large share of a stock 100-slot Postgres for a single-user install."
        )


class TestPostureConstantsMatchTheDeployedArtefact:

    def test_prod_web_worker_count_matches_railway_config(self):
        railway_ts = REPO_ROOT / ".railway" / "railway.ts"
        if not railway_ts.is_file():
            pytest.skip(reason=".railway/railway.ts is SaaS-only and absent from the CE export -- INF-9577")

        text = railway_ts.read_text(encoding="utf-8")
        match = re.search(r"WEB_CONCURRENCY:-(\d+)", text)
        assert match, ".railway/railway.ts no longer carries a WEB_CONCURRENCY default to pin against"

        declared = int(match.group(1))
        assert declared == REFERENCE_WEB_WORKERS, (
            f".railway/railway.ts now defaults WEB_CONCURRENCY to {declared}, but this module "
            f"still sizes the budget for {REFERENCE_WEB_WORKERS}. Re-run the arithmetic before "
            f"changing this constant — more workers means smaller per-worker pools, not "
            f"a bigger budget."
        )


class TestPoolWaitFailsFast:

    FAKE_URL = "postgresql://u:p@localhost:5432/giljo_inf9799_fake"

    def test_shipped_pool_timeout_is_five_seconds(self):
        assert DatabaseConfig().pg_pool_timeout == 5

    def test_async_engine_queue_pool_carries_the_timeout(self):
        from giljo_mcp.database import DatabaseManager

        assert DatabaseManager(self.FAKE_URL, is_async=True).async_engine.sync_engine.pool.timeout() == 5
        manager = DatabaseManager(self.FAKE_URL, is_async=True, pool_timeout=2)
        assert manager.async_engine.sync_engine.pool.timeout() == 2

    def test_sync_engine_queue_pool_carries_the_timeout(self):
        from giljo_mcp.database import DatabaseManager

        assert DatabaseManager(self.FAKE_URL, is_async=False).engine.pool.timeout() == 5
        assert DatabaseManager(self.FAKE_URL, is_async=False, pool_timeout=3).engine.pool.timeout() == 3

    def test_env_overrides_the_timeout(self, monkeypatch, tmp_path):
        from giljo_mcp.config_manager import ConfigManager

        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.setenv("GILJO_PG_POOL_TIMEOUT", "7")
        cfg = ConfigManager(config_path=tmp_path / "nonexistent.yaml", auto_reload=False)
        assert cfg.database.pg_pool_timeout == 7

    def test_config_yaml_postgres_pool_timeout_is_read(self, monkeypatch, tmp_path):
        from giljo_mcp.config_manager import ConfigManager

        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.delenv("GILJO_PG_POOL_TIMEOUT", raising=False)
        config_file = tmp_path / "config.yaml"
        config_file.write_text("database:\n  postgresql:\n    pool_timeout: 9\n", encoding="utf-8")
        cfg = ConfigManager(config_path=config_file, auto_reload=False)
        assert cfg.database.pg_pool_timeout == 9

    def test_create_database_manager_passes_the_timeout(self, monkeypatch, tmp_path):
        from giljo_mcp.config_manager import ConfigManager

        monkeypatch.setenv("DB_PASSWORD", "x")
        monkeypatch.setenv("GILJO_DATABASE_URL", self.FAKE_URL)
        monkeypatch.setenv("GILJO_PG_POOL_TIMEOUT", "4")
        cfg = ConfigManager(config_path=tmp_path / "nonexistent.yaml", auto_reload=False)
        assert cfg.create_database_manager().async_engine.sync_engine.pool.timeout() == 4

    @pytest.mark.asyncio
    async def test_boot_path_passes_the_configured_timeout(self, monkeypatch):
        from types import SimpleNamespace

        import api.startup.database as startup_db

        captured: dict = {}

        class _StopError(Exception):
            pass

        def _capture(*args, **kwargs):
            captured.update(kwargs)
            raise _StopError

        monkeypatch.setenv("DATABASE_URL", self.FAKE_URL)
        monkeypatch.setattr(
            startup_db, "get_config", lambda: SimpleNamespace(database=DatabaseConfig(pg_pool_timeout=3))
        )
        monkeypatch.setattr(startup_db, "DatabaseManager", _capture)

        with pytest.raises(_StopError):
            await startup_db.init_database(SimpleNamespace())
        assert captured["pool_timeout"] == 3
