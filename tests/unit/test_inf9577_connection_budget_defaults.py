# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9577 — the SHIPPED pool defaults must fit the real Postgres ceiling.

The startup budget check (``check_connection_budget``, INF-3009a/INF-3009f) already
existed and already worked. It was not the gap. The gap was that **nothing asserted
the shipped defaults pass at a realistic multi-worker posture**, so a bad default
could log a budget overrun on every boot with no test going red.

The pre-existing tests around this check all use invented numbers (50/50 over two
workers to prove it fires, 10/10 over one worker to prove it stays quiet). Neither
shape resembles a real deployment, so neither could catch a bad default.

These tests close that. They compute the worst case from the SHIPPED config defaults
against a documented REFERENCE POSTURE — a stronger invariant than the runtime
check, because the runtime check scores each service in isolation and no single
process can see the deployment-wide total.

The reference posture: 5 pool-opening processes against a stock 100-slot Postgres,
with ``superuser_reserved_connections = 3`` (the stock default). The reserved figure
is deliberately pessimistic — assuming fewer usable slots than there may be — so an
error there can only make the guard stricter.

These tests touch NO database and no network: they are arithmetic over config
defaults plus one call into the real logging check. Parallel-safe, no module-level
mutable state, no ordering dependencies.
"""

import re
from pathlib import Path

import pytest

from api.broker.postgres_notify import MAX_DB_CONNECTIONS_PER_PROCESS
from api.startup.database import _broker_direct_connections, check_connection_budget
from giljo_mcp.config_manager import DatabaseConfig


REPO_ROOT = Path(__file__).resolve().parents[2]

# --- The reference posture the defaults have to survive --------------------------
# A multi-worker web service plus a single-process worker service, both against the
# SAME Postgres. The web worker count comes from WEB_CONCURRENCY, whose single
# source of truth is the deployment config (asserted below where that file exists).
REFERENCE_WEB_WORKERS = 4
REFERENCE_WORKER_SERVICE_PROCESSES = 1

# Named so the assumption is reviewable rather than buried: the posture assumes one
# instance of each service. A second instance of either DOUBLES that service's
# contribution and invalidates every number below, and no runtime check would catch
# it because each process only ever sees its own worker count. That makes this a
# per-process pool decision, not a free knob.
REFERENCE_WEB_INSTANCES = 1
REFERENCE_WORKER_SERVICE_INSTANCES = 1

REFERENCE_POOL_OPENING_PROCESSES = (
    REFERENCE_WEB_WORKERS * REFERENCE_WEB_INSTANCES
    + REFERENCE_WORKER_SERVICE_PROCESSES * REFERENCE_WORKER_SERVICE_INSTANCES
)

# --- The ceiling -----------------------------------------------------------------
REFERENCE_MAX_CONNECTIONS = 100
SUPERUSER_RESERVED_CONNECTIONS = 3
USABLE_SLOTS = REFERENCE_MAX_CONNECTIONS - SUPERUSER_RESERVED_CONNECTIONS

# Connections that exist but are not pool config, so they cannot be computed from it:
# the pre-deploy migration step, an administrative psql session, and the one
# short-lived sync engine api/startup/migration_check.py opens per worker at boot
# and disposes immediately. The last of those cannot stack with the saturation case
# below (it runs while the pools are still cold), but reserving for all of them
# beats pretending the whole usable ceiling belongs to the pools.
OPERATIONAL_HEADROOM_SLOTS = 8

# CE is single-worker and single-user (ADR-009). It does not need SaaS's pool, but it
# must not be squeezed to where ordinary dashboard traffic serialises behind the pool.
CE_MIN_CONCURRENT_SESSIONS = 8


def _per_process_worst_case(cfg: DatabaseConfig, broker: int) -> int:
    """One process's ceiling: its SQLAlchemy pool plus the broker's out-of-pool connections.

    The broker connects with raw asyncpg outside the SQLAlchemy pool (1 session-pinned
    LISTEN + a publish pool), so it is additive to pool_size + max_overflow, never
    covered by it. This mirrors ``check_connection_budget``'s own arithmetic.
    """
    return cfg.pg_pool_size + cfg.pg_max_overflow + broker


class TestShippedDefaultsFitTheCeiling:
    """The invariant the shipped defaults must satisfy."""

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
        """The budget is a self-imposed number; this is the server's real one."""
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
        """A budget above the usable ceiling would pass every check and still exhaust the DB."""
        cfg = DatabaseConfig()
        assert cfg.pg_slot_budget <= USABLE_SLOTS, (
            f"pg_slot_budget {cfg.pg_slot_budget} exceeds the {USABLE_SLOTS} slots the "
            f"server actually has available; the budget would authorise an outage."
        )


class TestTheRuntimeCheckAgreesAtTheRealPosture:
    """DoD: the guard passes on the real config — and still fires on a known-bad one."""

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
        """Fire the checker on known-bad: the 10/10 config that shipped over budget.

        A guard that has never failed is not yet a guard. This pins the pre-INF-9577
        defaults as the known-bad case, so the arithmetic above cannot be satisfied by
        a check that quietly stopped working.
        """
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
        # The arithmetic the check reports: 4 x (10 + 10 + 6) + 0 = 104.
        assert any("= 104 connections > budget 90" in m for m in messages), messages


class TestCommunityEditionIsNotStarved:
    """CE runs ONE worker with the in-memory broker; state what it actually gets."""

    def test_ce_default_broker_costs_no_database_connections(self, monkeypatch):
        monkeypatch.delenv("GILJO_WS_BROKER", raising=False)
        monkeypatch.delenv("GILJO_WEBSOCKET_BROKER", raising=False)

        assert _broker_direct_connections(None) == 0

    def test_ce_single_worker_pool_does_not_serialise(self):
        cfg = DatabaseConfig()
        # CE: one process, in-memory broker, so the pool IS the whole footprint.
        ce_concurrent = cfg.pg_pool_size + cfg.pg_max_overflow

        assert ce_concurrent >= CE_MIN_CONCURRENT_SESSIONS, (
            f"CE would run on {ce_concurrent} concurrent DB sessions, below the "
            f"{CE_MIN_CONCURRENT_SESSIONS} floor a single-user dashboard needs before "
            f"ordinary traffic queues on pool_timeout."
        )

    def test_ce_single_worker_fits_a_stock_postgres_with_room_to_spare(self):
        cfg = DatabaseConfig()
        ce_total = cfg.pg_pool_size + cfg.pg_max_overflow

        # A self-hoster's Postgres is stock: 100 slots. CE must not need a tuned server.
        assert ce_total <= USABLE_SLOTS // 4, (
            f"CE's {ce_total} connections are a large share of a stock 100-slot Postgres for a single-user install."
        )


class TestPostureConstantsMatchTheDeployedArtefact:
    """Keep the numbers above honest against the file that actually sets them.

    railway.toml is SaaS-only and stripped from the CE export, so this pairing check
    skips where the artefact does not exist. The arithmetic tests above do not skip —
    they run in every edition.
    """

    def test_prod_web_worker_count_matches_railway_toml(self):
        railway_toml = REPO_ROOT / "railway.toml"
        if not railway_toml.is_file():
            pytest.skip(reason="railway.toml is SaaS-only and absent from the CE export -- INF-9577")

        text = railway_toml.read_text(encoding="utf-8")
        match = re.search(r"WEB_CONCURRENCY:-(\d+)", text)
        assert match, "railway.toml no longer carries a WEB_CONCURRENCY default to pin against"

        declared = int(match.group(1))
        assert declared == REFERENCE_WEB_WORKERS, (
            f"railway.toml now defaults WEB_CONCURRENCY to {declared}, but this module "
            f"still sizes the budget for {REFERENCE_WEB_WORKERS}. Re-run the arithmetic before "
            f"changing this constant — more workers means smaller per-worker pools, not "
            f"a bigger budget."
        )
