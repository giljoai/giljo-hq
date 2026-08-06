# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Pytest configuration for test suite
Provides test fixtures and database setup
"""

import asyncio
import contextlib
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event as _sa_event


# Add src to path
# TODO: Remove after editable install confirmed on all platforms
sys.path.insert(0, str(Path(__file__).parent.parent))

# Surface only the .env keys tests legitimately need (POSTGRES_SUPERUSER_PASSWORD).
# Loading the entire .env via load_dotenv() would inject the developer's
# production DATABASE_URL and trigger the test-suite's production-database
# safety guard. CI sets DATABASE_URL via secrets; locally we want the test
# helper to fall through to its DEFAULT_CONFIG using only the superuser
# password from .env.
try:
    from dotenv import dotenv_values as _dotenv_values

    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.is_file():
        _ENV_KEYS_TESTS_NEED = ("POSTGRES_SUPERUSER_PASSWORD",)
        _dotenv_pairs = _dotenv_values(_env_file)
        for _k in _ENV_KEYS_TESTS_NEED:
            _v = _dotenv_pairs.get(_k)
            if _v is not None and _k not in os.environ:
                os.environ[_k] = _v
except ImportError:
    pass

# Ensure config validation passes without real secrets
os.environ.setdefault("DB_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET", "test_secret_key")

# Import Product model for test_product fixture
from giljo_mcp.models import Product  # noqa: E402 -- must follow DATABASE_URL setup above
from giljo_mcp.services.project_service import ProjectService  # noqa: E402
from giljo_mcp.tenant import TenantManager  # noqa: E402

# Import PostgreSQL test fixtures from base_fixtures
from tests.fixtures.base_fixtures import (  # noqa: E402
    db_manager,
    db_session,
    test_project,
)


# Import pytest plugin for PostgreSQL database management
pytest_plugins = ["tests.pytest_postgresql_plugin"]

# Re-export fixtures so they're available to all tests
__all__ = [
    "db_manager",
    "db_session",
    "test_project",
]


@pytest.fixture
def event_loop():
    """
    Create event loop for async tests.

    Note: Using function scope to avoid event loop closed issues.
    Each test gets a fresh event loop for proper async isolation.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    # Cleanup pending tasks before closing
    with contextlib.suppress(Exception):
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()


@pytest.fixture(autouse=True)
def _reset_tenant_context_var():
    """Neutralize any tenant ContextVar leaked by a sibling test (BE6004C, xdist-safe).

    Under ``pytest-xdist -n auto`` each worker runs tests sequentially in one
    process. A test (or a sync fixture such as ``project_service_with_session``)
    that calls ``TenantManager.set_current_tenant(...)`` in the worker's *root*
    context and never resets it leaves that value live for every subsequent
    test in the same worker. Tests that legitimately expect NO ambient tenant
    (e.g. auth-revocation, mcp-scope-filtering, discovery, taxonomy) then read a
    stale foreign tenant and fail — but only under ``-n auto`` (they pass in
    isolation). This is the test-harness analog of Slice-1's middleware
    reset-at-entry.

    This is a SYNC fixture on purpose: the leak lives in the worker's root
    contextvars context (sync setters), which is what each async test's Task
    copies at creation time; clearing it here, before the test's Task is built
    and again after teardown, closes the cross-test channel. It only ever sets
    the var to ``None`` — it cannot mask a real bug, it only stops one test's
    leaked context from authorizing another test's queries. As an autouse
    fixture it runs before non-autouse fixtures at setup, so a test's own
    explicit ``set_current_tenant`` (via a requested fixture or its body) still
    wins for that test.
    """
    from giljo_mcp.tenant import current_tenant

    current_tenant.set(None)
    try:
        yield
    finally:
        current_tenant.set(None)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_agent_coordination(db_manager, db_session):
    """
    Auto-setup fixture to inject db_manager and session into agent_coordination module.

    This allows spawn_agent() to work in tests with proper
    session isolation (Handover 0366c).
    """
    from giljo_mcp.tools import agent_coordination

    agent_coordination.init_for_testing(db_manager, db_session)
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_context_module(db_manager):
    """
    Auto-setup fixture to inject db_manager into context module.

    This allows fetch_context() and other context tools to work in tests
    by setting the global _db_manager (Handover 0366c).
    Note: update_context_usage() was removed in Handover 0422 (dead token budget cleanup).
    """
    import giljo_mcp.database as db_module

    db_module.set_db_manager(db_manager)
    yield


# ---------------------------------------------------------------------------
# Committed-test-org leak teardown (BE-9238)
# ---------------------------------------------------------------------------
# Several API/security suites create Organization(...) + User(...) then COMMIT
# via a real ``db_manager.get_session_async()`` session (NOT the rollback-isolated
# ``db_session``) — deliberately, because the endpoint under test uses its own DB
# session, so a rolled-back org would be invisible to the request handler. With no
# teardown those rows persisted forever, leaking ~1,100 ``tk_`` org/user pairs into
# the shared test DB. The correct fix is TEARDOWN, not rollback: capture exactly
# the ``tk_`` tenant_keys this test's ORM inserts minted, then delete only those.
#
# xdist-safety (load-bearing — this fixture runs under ``-n auto``): each worker is
# a separate PROCESS with (a) its OWN per-worker database ``giljo_mcp_test_gwN``
# (see ``PostgreSQLTestHelper.resolve_test_db_name``) and (b) its own copy of the
# module-level set below. Captured tenant_keys are freshly-generated, globally
# unique random values (``tk_`` + 32 hex); the set is cleared at the start of every
# test; and cleanup runs against THIS test's own ``db_manager`` (its own DB). So a
# worker can only ever delete rows IT minted, in ITS OWN database — it is physically
# impossible to touch a sibling worker's in-flight rows. This is deliberately NOT a
# "delete every tk_ row created since a snapshot" — that could race a sibling.
_leaked_tenant_keys: set[str] = set()


def _capture_committed_tenant_key(_mapper, _connection, target) -> None:
    """``after_insert`` hook: record ``tk_`` tenant_keys of Organization/User inserts."""
    tenant_key = getattr(target, "tenant_key", None)
    if isinstance(tenant_key, str) and tenant_key.startswith("tk_"):
        _leaked_tenant_keys.add(tenant_key)


def _register_tenant_key_capture() -> None:
    """Attach the capture hook once per worker process (idempotent)."""
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization

    for model in (Organization, User):
        if not _sa_event.contains(model, "after_insert", _capture_committed_tenant_key):
            _sa_event.listen(model, "after_insert", _capture_committed_tenant_key)


_register_tenant_key_capture()


async def _purge_tenant_key(db_manager, tenant_key: str) -> None:
    """Delete every row for a single ``tk_`` tenant across all tenant-scoped tables.

    Runs FK-safe and list-free: it walks ``Base.metadata.sorted_tables`` in reverse
    (dependency order is parents-before-children, so reversed is children-before-
    parents — the correct order to delete without tripping a foreign key) and issues
    a ``DELETE ... WHERE tenant_key = :tk`` against every table that carries a
    ``tenant_key`` column. Because the order comes from the schema itself, this stays
    correct no matter which tables a test committed into (project + task, comm thread,
    product memory, roadmap, ...), with no hand-maintained model list to fall stale.

    SCHEMA-AWARE: the ORM metadata also carries SaaS-only tables (e.g. ``restore_requests``,
    created only by ``migrations/saas_versions/``) that are ABSENT from a CE-schema test
    DB — CI's CE pytest job builds its DB from ``migrations/versions/`` alone. A blind
    ``DELETE FROM`` on such a table raises ``UndefinedTableError`` there, so we first
    intersect the metadata tables with the tables that PHYSICALLY EXIST in the connected
    database (``pg_tables``). This keeps the purge correct on every schema — CE, SaaS, and
    the local create_all test DBs alike — instead of only the schema the author's DB
    happens to carry.

    Uses a raw superuser connection from the test engine, which deliberately bypasses
    the ORM tenant-isolation guard — this is a test-only cleanup of ONE known,
    globally-unique test tenant, not app code. ``table.name`` comes from our own
    metadata (never user input), so the interpolated identifier is safe.
    """
    from sqlalchemy import text

    from giljo_mcp.models.base import Base

    async with db_manager.async_engine.begin() as conn:
        result = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        existing_tables = {row[0] for row in result}
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in existing_tables and "tenant_key" in table.c:
                await conn.execute(
                    text(f'DELETE FROM "{table.name}" WHERE tenant_key = :tk'),
                    {"tk": tenant_key},
                )


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _purge_committed_test_orgs(db_manager):
    """Delete the ``tk_`` rows this test COMMITTED (BE-9238 leak fix).

    Parallel-safe by construction (see the module note above): only this test's own
    freshly-minted ``tk_`` tenant_keys are deleted, and only in this worker's own
    per-worker DB. Inserts that were rolled back (the ``db_session`` isolation
    fixture) never persist, so their delete is a harmless 0-row no-op. The whole
    tenant is purged FK-safely (see ``_purge_tenant_key``), so a test that commits a
    project/task/etc. under its tk_ tenant is cleaned completely, not just its org.
    """
    _leaked_tenant_keys.clear()
    try:
        yield
    finally:
        keys = list(_leaked_tenant_keys)
        _leaked_tenant_keys.clear()
        for tenant_key in keys:
            await _purge_tenant_key(db_manager, tenant_key)


@pytest.fixture
def real_auth_rate_limiter():
    """Opt OUT of the global pre-auth rate-limit test bypass for this test.

    SEC-9227 (H4): the pre-auth limiter's test bypass is an explicit
    process-local flag (``auth_rate_limits.set_test_bypass``), not the old
    forgeable ``Host: http://test`` sentinel. The autouse
    ``_auth_rate_limit_test_bypass`` fixture below turns that bypass ON for the
    whole suite so tests are not throttled — but a suite that exercises the
    limiter ITSELF must run against the real limiter. Requesting this fixture
    (directly or via a class/module autouse) keeps the bypass OFF for that test;
    the autouse fixture detects the request and stands down.
    """
    from api.middleware.auth_rate_limits import set_test_bypass

    set_test_bypass(False)
    try:
        yield
    finally:
        set_test_bypass(False)


@pytest.fixture(autouse=True)
def _auth_rate_limit_test_bypass(request):
    """Bypass the pre-auth IP rate limiter for the suite (SEC-9227 H4).

    The limiter's bypass is now an explicit process-local flag rather than a
    ``Host``-header sentinel, so the suite must set it itself — the TestClient
    default ``http://testserver`` no longer short-circuits the limiter. Enabled
    for every test EXCEPT those that request ``real_auth_rate_limiter`` (the
    rate-limit suites), which own the flag and keep it off. The opt-out is read
    from ``request.fixturenames`` (resolved at setup), so this never fights the
    opt-out fixture on ordering — when the opt-out is present this fixture does
    not touch the flag at all.
    """
    from api.middleware.auth_rate_limits import set_test_bypass

    if "real_auth_rate_limiter" in request.fixturenames:
        yield
        return
    set_test_bypass(True)
    try:
        yield
    finally:
        set_test_bypass(False)


# Note: db_session fixture is imported from base_fixtures.py
# and provides transaction-based test isolation


@pytest_asyncio.fixture(scope="function")
async def tenant_manager() -> TenantManager:
    """Create tenant manager for testing"""
    return TenantManager()


@pytest_asyncio.fixture(scope="function")
async def project_service_with_session(db_session, db_manager, tenant_manager, test_tenant_key):
    """ProjectService using shared test session for E2E/integration tests."""
    # Set the tenant context for the service
    tenant_manager.set_current_tenant(test_tenant_key)
    return ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )


# Note: db_manager fixture is imported from base_fixtures.py above


@pytest_asyncio.fixture(scope="function")
async def test_tenant_key():
    """Generate a test tenant key"""
    from giljo_mcp.tenant import TenantManager

    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture(scope="function")
async def test_project_id(db_session, test_tenant_key):
    """Create a test project and return its ID"""
    import random
    import uuid

    from giljo_mcp.models import Project

    project = Project(
        id=str(uuid.uuid4()),
        name="Test Project",
        description="Test project description for integration testing",
        mission="Test mission for integration testing",
        status="active",
        tenant_key=test_tenant_key,
        series_number=random.randint(1, 9000),
    )

    db_session.add(project)
    await db_session.commit()
    db_session.info["tenant_key"] = test_tenant_key

    return project.id


@pytest_asyncio.fixture(scope="function")
async def test_product(db_session, test_tenant_key):
    """Create a test product for testing."""
    import uuid

    product = Product(
        id=str(uuid.uuid4()),
        name="Test Product",
        description="Test product for repository testing",
        tenant_key=test_tenant_key,
        is_active=True,
        product_memory={},
    )

    db_session.add(product)
    await db_session.commit()
    db_session.info["tenant_key"] = test_tenant_key
    await db_session.refresh(
        product,
        attribute_names=["tech_stack", "architecture", "test_config", "vision_documents"],
    )

    return product


def pytest_configure(config):
    """
    Pytest hook to configure test session.

    Registers custom markers and disables coverage threshold enforcement
    for smoke tests, since they are integration workflow validators
    (not unit coverage targets).

    CRITICAL SAFETY: Also validates that tests cannot access production database.
    """
    # ==========================================================================
    # PRODUCTION DATABASE SAFETY GUARD
    # ==========================================================================
    # Verify environment is set up for testing, not production
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url and "/giljo_mcp" in db_url and "/giljo_mcp_test" not in db_url:
        import warnings

        warnings.warn(
            f"WARNING: DATABASE_URL appears to point to production database!\n"
            f"Tests should use giljo_mcp_test, not giljo_mcp.\n"
            f"Current DATABASE_URL: {db_url[:50]}...",
            UserWarning,
            stacklevel=2,
        )

    # Register custom markers
    config.addinivalue_line(
        "markers", "tenant_isolation: marks tests for tenant isolation verification (Handover 0325)"
    )
    config.addinivalue_line(
        "markers", "production_safe: marks tests that have been verified safe from production DB access"
    )

    # BE-9288: an un-awaited AsyncMock coroutine is a real test-double bug (a
    # mock session/manager left under-specified lets a sync-in-real-SQLAlchemy
    # call -- e.g. Result.scalar_one_or_none(), Session.info.get() -- come back
    # async and silently go unawaited). Narrow on purpose: only THIS exact
    # message becomes an error, so it fails the offending test loudly instead
    # of relying on someone noticing the warning.
    #
    # TWO filters, not one: the coroutine's own finalizer (coro_dealloc) raises
    # the "never awaited" RuntimeWarning from INSIDE a destructor, so CPython
    # cannot let it propagate as a normal exception -- it reports it via
    # sys.unraisablehook instead (verified empirically: filtering only
    # RuntimeWarning leaves the test passing, just with different warning
    # text). Pytest's builtin unraisableexception plugin re-wraps whatever
    # sys.unraisablehook receives as PytestUnraisableExceptionWarning; THAT is
    # the one that must become the error for the test to actually fail.
    config.addinivalue_line("filterwarnings", "error:coroutine .* was never awaited:RuntimeWarning")
    # No literal ':' in the message half -- pytest's filterwarnings parser
    # splits the whole "action:message:category:..." spec on ':' with no
    # escaping, so a literal colon there breaks parsing. '.' (any char)
    # stands in for the "ignored in:" colon instead.
    config.addinivalue_line(
        "filterwarnings",
        "error:.*coroutine object AsyncMockMixin._execute_mock_call:pytest.PytestUnraisableExceptionWarning",
    )

    # Check if we're only running smoke tests
    selected_tests = config.getoption("file_or_dir", default=[])
    markers = config.getoption("-m", default="")

    # If running smoke tests specifically, disable fail_under threshold
    if "smoke" in markers or any("smoke" in str(test) for test in selected_tests):
        # Store original fail_under value
        if hasattr(config, "_coverage_config"):
            # Access coverage plugin configuration
            try:
                cov_plugin = config.pluginmanager.get_plugin("_cov")
                if cov_plugin and hasattr(cov_plugin, "cov_controller"):
                    # Disable fail_under for smoke tests
                    cov_config = cov_plugin.cov_controller.cov.config
                    if hasattr(cov_config, "fail_under"):
                        cov_config.fail_under = None
            except (AttributeError, KeyError):
                # Coverage plugin not loaded or configured differently
                pass
