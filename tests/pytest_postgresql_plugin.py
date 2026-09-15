# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import os
import re
import sys

import pytest


PRODUCTION_DB_NAME = "giljo_mcp"
TEST_DB_NAME = "giljo_mcp_test"
SAFETY_ENV_VAR = "GILJO_TEST_SAFE"

SHARED_BASE_OVERRIDE_ENV_VAR = "GILJO_ALLOW_SHARED_TEST_DB"


class ProductionDatabaseProtectionError(Exception):
    pass


class SharedTestDatabaseError(pytest.UsageError):
    pass


def _check_database_safety() -> tuple[bool, str]:
    if os.environ.get(SAFETY_ENV_VAR) == "1":
        return True, "Safety bypass enabled via GILJO_TEST_SAFE=1"

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
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
        pass

    return True, "Environment appears safe for testing"


def resolved_target_database() -> tuple[str, str]:
    source = "DATABASE_URL" if os.environ.get("DATABASE_URL") else "DEFAULT_CONFIG (DATABASE_URL unset)"
    try:
        from tests.helpers.test_db_helper import PostgreSQLTestHelper

        return PostgreSQLTestHelper.resolve_test_db_name(), source
    except ImportError:
        return "UNKNOWN (tests.helpers.test_db_helper did not import)", source


def _xdist_active(config) -> bool:
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return True
    numprocesses = getattr(config.option, "numprocesses", None)
    return numprocesses not in (None, 0, "0")


def _shared_base_verdict(resolved_db: str, xdist: bool) -> tuple[str, str] | None:
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
    lines = _banner_lines(is_safe, message, target, source, advisory, advisory_level)
    print("\n" + "\n".join(lines) + "\n", file=sys.stderr)


def pytest_addoption(parser):
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
    config.addinivalue_line("markers", "postgresql: mark test as requiring PostgreSQL database")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "production_safe: mark test as verified safe from production DB access")

    if config.getoption("--skip-db-safety-check", default=False):
        print("\n⚠️  WARNING: Database safety check SKIPPED (--skip-db-safety-check)\n", file=sys.stderr)
        return

    is_safe, message = _check_database_safety()
    target, source = resolved_target_database()

    verdict = _shared_base_verdict(target, _xdist_active(config))
    advisory, advisory_level = "", ""
    if verdict:
        advisory_level, advisory = verdict
        if advisory_level == "FAIL" and os.environ.get(SHARED_BASE_OVERRIDE_ENV_VAR) == "1":
            advisory_level = "WARN"
            advisory = f"{advisory}\n(Refusal overridden by {SHARED_BASE_OVERRIDE_ENV_VAR}=1.)"
        verdict = (advisory_level, advisory)

    _print_safety_banner(is_safe, message, target, source, advisory, advisory_level)

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
    if session.config.getoption("--drop-test-db"):
        print("\n\nDropping test database...")

        async def drop_db():
            from tests.helpers.test_db_helper import PostgreSQLTestHelper

            try:
                await PostgreSQLTestHelper.drop_test_database()
                print("Test database dropped successfully")
            except Exception as e:
                print(f"Error dropping test database: {e}")

        asyncio.run(drop_db())


def pytest_collection_modifyitems(config, items):
    for item in items:
        item.add_marker(pytest.mark.postgresql)

        if "slow" in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)
