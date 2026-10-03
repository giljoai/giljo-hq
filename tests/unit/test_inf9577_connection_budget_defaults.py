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
