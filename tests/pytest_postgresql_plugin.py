# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Pytest plugin for PostgreSQL test database management.

Provides command-line options for managing the test database.

CRITICAL SAFETY: This plugin includes a HARD BLOCK that prevents tests
from running if they could potentially hit the production database.
Tests will ABORT before collection if the environment is unsafe.
"""

import asyncio
import os
import re
import sys

import pytest


# =============================================================================
# PRODUCTION DATABASE SAFETY CONSTANTS
# =============================================================================
PRODUCTION_DB_NAME = "giljo_mcp"
TEST_DB_NAME = "giljo_mcp_test"
SAFETY_ENV_VAR = "GILJO_TEST_SAFE"

# Opt-out for the shared-base refusal below. Deliberately distinct from
# SAFETY_ENV_VAR: that one waives PRODUCTION protection, this one waives LANE
# isolation, and someone who needs the second must not be nudged into disabling
# the first.
SHARED_BASE_OVERRIDE_ENV_VAR = "GILJO_ALLOW_SHARED_TEST_DB"


class ProductionDatabaseProtectionError(Exception):
    """Raised when tests might accidentally hit production database."""


class SharedTestDatabaseError(pytest.UsageError):
    """Raised when a numbered clone would run xdist against the SHARED test-DB base.

    Distinct from :class:`ProductionDatabaseProtectionError`: no production data is
    at risk here. What is at risk is every concurrent lane's run, including this
    one — see :func:`_shared_base_verdict`.

    Deliberately a :class:`pytest.UsageError` subclass rather than a bare
    ``Exception``. A plain exception raised from ``pytest_configure`` surfaces as
    ``INTERNALERROR>`` followed by a pluggy traceback, which reads as "the test
    harness is broken" and buries the actionable line under stack frames — measured
    on the first implementation of this refusal. It is not an internal error: the
    invocation is wrong and the fix is a command-line change, which is precisely
    what ``UsageError`` means. Subclassing keeps pytest's clean single-line ``ERROR``
    output while leaving the type nameable by the regression test.
    """


def _check_database_safety() -> tuple[bool, str]:
    """
    Check if the test environment is safe (not pointing to production).

    Returns:
        tuple: (is_safe: bool, message: str)
    """
    # Check 1: Is safety bypass explicitly enabled?
    if os.environ.get(SAFETY_ENV_VAR) == "1":
        return True, "Safety bypass enabled via GILJO_TEST_SAFE=1"

    # Check 2: Is DATABASE_URL set and pointing to production?
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        # Check if it contains production DB name without _test
        if f"/{PRODUCTION_DB_NAME}" in db_url and f"/{TEST_DB_NAME}" not in db_url:
            return False, (
                f"DATABASE_URL points to production database '{PRODUCTION_DB_NAME}'!\n"
                f"  Expected: URL containing '{TEST_DB_NAME}'\n"
                f"  (Run `echo $DATABASE_URL` to inspect the actual value.)\n\n"
                f"To fix:\n"
                f"  1. Unset DATABASE_URL: unset DATABASE_URL\n"
                f"  2. Or set it to test DB: export DATABASE_URL=postgresql://.../{TEST_DB_NAME}\n"
                f"  3. Or bypass (DANGEROUS): export {SAFETY_ENV_VAR}=1"
            )

    # Check 3: Verify test helper defaults are correct
    try:
        from tests.helpers.test_db_helper import PostgreSQLTestHelper

        default_db = PostgreSQLTestHelper.DEFAULT_CONFIG.get("database", "")
        if default_db != TEST_DB_NAME:
            return False, (
                f"Test helper default database is not '{TEST_DB_NAME}'!\n"
                f"  Found: {default_db}\n"
                f"  This is a code bug - fix test_db_helper.py"
            )
    except ImportError:
        # If we can't import the helper, that's a different problem
        pass

    return True, "Environment appears safe for testing"


def resolved_target_database() -> tuple[str, str]:
    """The database this process will ACTUALLY connect to, and where that came from.

    Returns ``(database, source)`` — e.g. ``("giljo_mcp_test2_gw3", "DATABASE_URL")``.

    THE POINT OF THIS FUNCTION (INF-9432). The safety banner used to interpolate the
    module constant :data:`TEST_DB_NAME`, so it printed ``giljo_mcp_test`` on every
    run of every tree — under a numbered-clone pin, under bare pytest, and in CI,
    where the real base is ``giljo_test``. Measured: three runs whose real targets
    were ``giljo_mcp_test2``, ``giljo_mcp_test``, and ``giljo_test`` produced
    byte-identical banner text. The line was not occasionally stale, it was
    incapable of being right except by coincidence on the unnumbered default.

    That made it worse than silent. A lane that pinned correctly read the banner,
    saw the shared base named, and concluded its pin had not taken — so the sprint
    that found this had a standing rule telling every lane to verify the target in
    ``pg_database`` and ignore the instrument. An instrument nobody may believe
    should either be deleted or made true; this makes it true.

    It resolves through :meth:`PostgreSQLTestHelper.resolve_test_db_name` — the same
    call the suite's own connections go through — rather than re-deriving from
    ``DATABASE_URL`` here. A second derivation is free to drift from the first, and
    a banner that drifts is back to lying with extra steps.

    KNOWN LIMIT, stated rather than left to be discovered: this is a SNAPSHOT taken
    in ``pytest_configure``, so it is true of the session as configured. A fixture
    that repointed ``DATABASE_URL`` mid-session would make the printed line stale --
    accurate when printed, no longer current. Nothing in the suite does that today
    outside of monkeypatched, function-scoped tests of this very function, which
    restore at teardown. Worth knowing before someone adds a fixture that does.
    """
    source = "DATABASE_URL" if os.environ.get("DATABASE_URL") else "DEFAULT_CONFIG (DATABASE_URL unset)"
    try:
        from tests.helpers.test_db_helper import PostgreSQLTestHelper

        return PostgreSQLTestHelper.resolve_test_db_name(), source
    except ImportError:
        # Same posture as _check_database_safety's Check 3: an unimportable helper is
        # a different problem, and must not turn into a misleading banner.
        return "UNKNOWN (tests.helpers.test_db_helper did not import)", source


def _xdist_active(config) -> bool:
    """True when this session is running xdist workers (or IS one).

    Both directions matter. ``pytest_configure`` runs in the controller AND in every
    worker; the controller knows only ``-n``, and a worker knows only its own
    ``PYTEST_XDIST_WORKER``. Checking one gives a verdict that is right in one
    process and wrong in the others.

    Any non-zero ``numprocesses`` counts, including the unresolved strings ``auto``
    and ``logical``: xdist normalises those in its own ``pytest_configure``, and
    plugin ordering between it and this file is not guaranteed, so this must not
    depend on having seen the resolved integer.
    """
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return True
    numprocesses = getattr(config.option, "numprocesses", None)
    return numprocesses not in (None, 0, "0")


def _shared_base_verdict(resolved_db: str, xdist: bool) -> tuple[str, str] | None:
    """Judge the resolved target against the lane-isolation law. ``None`` when fine.

    Returns ``("FAIL"|"WARN", explanation)``.

    THE DEFECT, in one line: on the shared unnumbered base, "my databases" and
    "everyone's databases" are the SAME STRING, so lane identity is unrepresentable
    and no amount of care downstream can recover it.

    Concurrent lanes sharing ``giljo_mcp_test_gw0..gwN`` is not a hypothetical.
    Its measured signature is ``UniqueViolation`` on ``pg_type_typname_nsp_index``
    (two workers copying ``template1`` into one database) and ``UndefinedTable`` on
    a table another process had just dropped — *a different victim every run*, which
    is exactly why it reads as ambient flakiness rather than as an isolation bug.

    Why the condition is this narrow, each clause load-bearing:

    * **Only the WORKSTATION shared base.** CI's base is ``giljo_test`` — read off
      ``.github/workflows/ci.yml``, where all four jobs set
      ``…@postgres:5432/giljo_test`` — so CI can never reach this branch. That is
      structural, not a hope: CI also gets a fresh empty Postgres per run, so a
      shared base there is correct rather than dangerous.
    * **Only under xdist.** Serial runs mutate one database in one process. Sharing
      is risky there and corrupting here, and a gate that fires on merely-risky
      would be argued around within a week.
    * **FAIL only when the tree HAS a lane to use.** A numbered clone on the shared
      base is an unambiguous mistake and the message can name the exact base it
      should have pinned, because the directory says so. An unnumbered tree (the
      primary checkout) has no better base to be told to
      use, so it gets a loud line and keeps its historical behaviour — breaking a
      correct habit to enforce a rule that does not apply to it would be the kind
      of collateral that gets a guard disabled rather than satisfied.
    """
    base = re.sub(r"_gw\d+$", "", resolved_db)
    if base != TEST_DB_NAME or not xdist:
        return None

    try:
        from tests.helpers.test_db_helper import clone_dir_slot

        dir_slot = clone_dir_slot()
    except ImportError:
        dir_slot = ""

    if not dir_slot:
        return (
            "WARN",
            f"SHARED test-DB base '{TEST_DB_NAME}' under xdist. This tree is not a numbered clone, "
            f"so it has no lane base of its own — but any clone_CI<N> clone running now shares "
            f"these '{TEST_DB_NAME}_gwN' databases with you.",
        )

    intended = f"{TEST_DB_NAME}{dir_slot}"
    return (
        "FAIL",
        f"This clone is CI{dir_slot}, so its test-DB base is '{intended}' — but this run resolved to "
        f"the SHARED base '{TEST_DB_NAME}' and xdist is active. Every other lane on this Postgres uses "
        f"the same '{TEST_DB_NAME}_gwN' databases, and the workers create, drop and migrate schema in "
        f"them. Fix: export DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/{intended}, or run "
        f"this repo's local suite wrapper, which pins the base for you. To proceed anyway (you are "
        f"certain no sibling lane is running): {SHARED_BASE_OVERRIDE_ENV_VAR}=1.",
    )


_BANNER_WIDTH = 66


def _banner_row(text: str) -> str:
    """One padded row of the banner box, truncated so a long value cannot break it."""
    inner = _BANNER_WIDTH - 1
    return f"║ {text[:inner]:<{inner}}║"


def _banner_lines(
    is_safe: bool,
    message: str,
    target: str,
    source: str,
    advisory: str = "",
    advisory_level: str = "",
) -> list[str]:
    """Build the safety banner. Split out from printing so a test can read it.

    ``advisory_level`` is ``"FAIL"``, ``"WARN"`` or ``""``. It drives the HEADER, not
    just a footnote: the first implementation of the lane refusal printed
    "✓ … PASSED" and then aborted the session, which is the same genre of lying
    instrument this project exists to remove — a banner whose headline contradicts
    what the run then does.
    """
    top = f"╔{'═' * _BANNER_WIDTH}╗"
    mid = f"╠{'═' * _BANNER_WIDTH}╣"
    bottom = f"╚{'═' * _BANNER_WIDTH}╝"

    if is_safe:
        if advisory_level == "FAIL":
            header = " ✗ LANE ISOLATION CHECK FAILED - TESTS ABORTED"
        elif advisory_level == "WARN":
            header = " ⚠ DATABASE SAFETY CHECK PASSED - LANE ISOLATION WARNING"
        else:
            header = " ✓ DATABASE SAFETY CHECK PASSED"
        rows = [
            top,
            _banner_row(header),
            _banner_row(f"   {message}"),
            _banner_row(f"   Target database: {target}"),
            _banner_row(f"   Resolved from:   {source}"),
        ]
        if advisory:
            rows.append(mid)
            rows.append(_banner_row(" ⚠ LANE ISOLATION" if advisory_level == "WARN" else " ✗ LANE ISOLATION"))
            rows.extend(_banner_row(f"   {chunk}") for chunk in _wrap(advisory))
        rows.append(bottom)
        return rows

    return [
        top,
        _banner_row(" ✗ DATABASE SAFETY CHECK FAILED - TESTS ABORTED"),
        mid,
        _banner_row(" DANGER: Tests could potentially modify production database!"),
        _banner_row(""),
        _banner_row(f" Target database: {target}  (from {source})"),
        _banner_row(""),
        *(_banner_row(f" {chunk}") for chunk in _wrap(message)),
        bottom,
    ]


def _wrap(text: str) -> list[str]:
    """Wrap to the banner's inner width, keeping explicit newlines as breaks."""
    import textwrap

    out: list[str] = []
    for paragraph in text.splitlines() or [""]:
        out.extend(textwrap.wrap(paragraph, width=_BANNER_WIDTH - 5) or [""])
    return out


def _print_safety_banner(
    is_safe: bool,
    message: str,
    target: str,
    source: str,
    advisory: str = "",
    advisory_level: str = "",
):
    """Print a visible safety status banner naming the RESOLVED target database."""
    lines = _banner_lines(is_safe, message, target, source, advisory, advisory_level)
    print("\n" + "\n".join(lines) + "\n", file=sys.stderr)


def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--drop-test-db",
        action="store_true",
        default=False,
        help="Drop the test database after test run completes",
    )
    parser.addoption(
        "--create-test-db",
        action="store_true",
        default=False,
        help="Create the test database before running tests (happens automatically)",
    )
    parser.addoption(
        "--skip-db-safety-check",
        action="store_true",
        default=False,
        help="Skip database safety check (DANGEROUS - use only if you know what you're doing)",
    )


def pytest_configure(config):
    """
    Configure pytest with custom markers and SAFETY CHECKS.

    CRITICAL: This runs before any tests are collected.
    If the environment is unsafe, we abort the entire test session.
    """
    # Register markers
    config.addinivalue_line("markers", "postgresql: mark test as requiring PostgreSQL database")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "production_safe: mark test as verified safe from production DB access")

    # ==========================================================================
    # HARD SAFETY CHECK - ABORT IF ENVIRONMENT IS UNSAFE
    # ==========================================================================
    # Skip check if explicitly requested (for special cases)
    if config.getoption("--skip-db-safety-check", default=False):
        print("\n⚠️  WARNING: Database safety check SKIPPED (--skip-db-safety-check)\n", file=sys.stderr)
        return

    is_safe, message = _check_database_safety()
    target, source = resolved_target_database()

    # LANE ISOLATION (INF-9432). Judged separately from production safety and
    # reported on the same banner, so the one instrument tells the whole truth
    # about where this run is about to write.
    verdict = _shared_base_verdict(target, _xdist_active(config))
    advisory, advisory_level = "", ""
    if verdict:
        advisory_level, advisory = verdict
        if advisory_level == "FAIL" and os.environ.get(SHARED_BASE_OVERRIDE_ENV_VAR) == "1":
            advisory_level = "WARN"
            advisory = f"{advisory}\n(Refusal overridden by {SHARED_BASE_OVERRIDE_ENV_VAR}=1.)"
        verdict = (advisory_level, advisory)

    _print_safety_banner(is_safe, message, target, source, advisory, advisory_level)

    # Production protection is raised FIRST when both fire: a run pointed at
    # production must report that, not a lane-isolation complaint about it.
    if is_safe and verdict and verdict[0] == "FAIL":
        raise SharedTestDatabaseError(
            f"\n\n"
            f"{'=' * 70}\n"
            f"TESTS ABORTED: shared test-database base under parallel execution.\n"
            f"{'=' * 70}\n\n"
            f"{verdict[1]}\n\n"
            f"{'=' * 70}\n"
        )

    if not is_safe:
        # ABORT THE TEST SESSION
        raise ProductionDatabaseProtectionError(
            f"\n\n"
            f"{'=' * 70}\n"
            f"TESTS ABORTED: Production database protection triggered!\n"
            f"{'=' * 70}\n\n"
            f"{message}\n\n"
            f"This is a safety feature to prevent accidental data loss.\n"
            f"{'=' * 70}\n"
        )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """
    Hook that runs after all tests are complete.

    If --drop-test-db flag is set, drops the test database.
    """
    if session.config.getoption("--drop-test-db"):
        print("\n\nDropping test database...")

        async def drop_db():
            from tests.helpers.test_db_helper import PostgreSQLTestHelper

            try:
                await PostgreSQLTestHelper.drop_test_database()
                print("Test database dropped successfully")
            except Exception as e:
                print(f"Error dropping test database: {e}")

        # Run the async drop operation
        asyncio.run(drop_db())


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection to add markers based on test characteristics.
    """
    for item in items:
        # Add postgresql marker to all tests (since we only use PostgreSQL now)
        item.add_marker(pytest.mark.postgresql)

        # Mark tests with "slow" in their name as slow
        if "slow" in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)
