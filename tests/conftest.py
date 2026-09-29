# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import contextlib
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event as _sa_event


sys.path.insert(0, str(Path(__file__).parent.parent))

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

os.environ.setdefault("DB_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET", "test_secret_key")

from giljo_mcp.models import Product  # noqa: E402 -- must follow DATABASE_URL setup above
from giljo_mcp.services.project_service import ProjectService  # noqa: E402
from giljo_mcp.tenant import TenantManager  # noqa: E402

from tests.fixtures.base_fixtures import (  # noqa: E402
    db_manager,
    db_session,
    restored_global_client_resolver,
    restored_global_protected_surface_patterns,
    restored_global_terms_accepted_check,
    restored_global_wake_relay,
    test_project,
)


pytest_plugins = ["tests.pytest_postgresql_plugin"]

__all__ = [
    "db_manager",
    "db_session",
    "test_project",
]


@pytest.fixture
def event_loop():
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    with contextlib.suppress(Exception):
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()


@pytest.fixture(autouse=True)
def _reset_tenant_context_var():
    from giljo_mcp.tenant import current_tenant

    current_tenant.set(None)
    try:
        yield
    finally:
        current_tenant.set(None)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_agent_coordination(db_manager, db_session):
    from giljo_mcp.tools import agent_coordination

    agent_coordination.init_for_testing(db_manager, db_session)
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_context_module(db_manager):
    import giljo_mcp.database as db_module

    db_module.set_db_manager(db_manager)
    yield


_leaked_tenant_keys: set[str] = set()


def _capture_committed_tenant_key(_mapper, _connection, target) -> None:
    tenant_key = getattr(target, "tenant_key", None)
    if isinstance(tenant_key, str) and tenant_key.startswith("tk_"):
        _leaked_tenant_keys.add(tenant_key)


def _register_tenant_key_capture() -> None:
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization

    for model in (Organization, User):
        if not _sa_event.contains(model, "after_insert", _capture_committed_tenant_key):
            _sa_event.listen(model, "after_insert", _capture_committed_tenant_key)


_register_tenant_key_capture()


async def _purge_tenant_key(db_manager, tenant_key: str) -> None:
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
    from api.middleware.auth_rate_limits import set_test_bypass

    set_test_bypass(False)
    try:
        yield
    finally:
        set_test_bypass(False)


@pytest.fixture(autouse=True)
def _auth_rate_limit_test_bypass(request):
    from api.middleware.auth_rate_limits import set_test_bypass

    if "real_auth_rate_limiter" in request.fixturenames:
        yield
        return
    set_test_bypass(True)
    try:
        yield
    finally:
        set_test_bypass(False)


@pytest.fixture
def real_rate_limiter():
    from api.middleware.rate_limiter import set_test_bypass

    set_test_bypass(False)
    try:
        yield
    finally:
        set_test_bypass(False)


@pytest.fixture(autouse=True)
def _general_rate_limit_test_bypass(request):
    from api.middleware.rate_limiter import set_test_bypass

    if "real_rate_limiter" in request.fixturenames:
        yield
        return
    set_test_bypass(True)
    try:
        yield
    finally:
        set_test_bypass(False)


@pytest.fixture(autouse=True)
def _restore_global_wake_relay():
    with restored_global_wake_relay():
        yield


@pytest.fixture(autouse=True)
def _restore_global_client_resolver():
    with restored_global_client_resolver():
        yield


@pytest.fixture(autouse=True)
def _restore_global_terms_accepted_check():
    with restored_global_terms_accepted_check():
        yield


@pytest.fixture(autouse=True)
def _restore_global_protected_surface_patterns():
    with restored_global_protected_surface_patterns():
        yield




@pytest_asyncio.fixture(scope="function")
async def tenant_manager() -> TenantManager:
    return TenantManager()


@pytest_asyncio.fixture(scope="function")
async def project_service_with_session(db_session, db_manager, tenant_manager, test_tenant_key):
    tenant_manager.set_current_tenant(test_tenant_key)
    return ProjectService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=db_session,
    )




@pytest_asyncio.fixture(scope="function")
async def test_tenant_key():
    from giljo_mcp.tenant import TenantManager

    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture(scope="function")
async def test_project_id(db_session, test_tenant_key):
    import random
    import uuid

    from giljo_mcp.models import Product, Project

    product = Product(
        id=str(uuid.uuid4()),
        name=f"Test Project's Product {uuid.uuid4().hex[:6]}",
        description="Owning product for the test project fixture",
        tenant_key=test_tenant_key,
        is_active=False,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        product_id=product.id,
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

    config.addinivalue_line(
        "markers", "tenant_isolation: marks tests for tenant isolation verification (Handover 0325)"
    )
    config.addinivalue_line(
        "markers", "production_safe: marks tests that have been verified safe from production DB access"
    )

    config.addinivalue_line("filterwarnings", "error:coroutine .* was never awaited:RuntimeWarning")
    config.addinivalue_line(
        "filterwarnings",
        "error:.*coroutine object AsyncMockMixin._execute_mock_call:pytest.PytestUnraisableExceptionWarning",
    )

    selected_tests = config.getoption("file_or_dir", default=[])
    markers = config.getoption("-m", default="")

    if "smoke" in markers or any("smoke" in str(test) for test in selected_tests):
        if hasattr(config, "_coverage_config"):
            try:
                cov_plugin = config.pluginmanager.get_plugin("_cov")
                if cov_plugin and hasattr(cov_plugin, "cov_controller"):
                    cov_config = cov_plugin.cov_controller.cov.config
                    if hasattr(cov_config, "fail_under"):
                        cov_config.fail_under = None
            except (AttributeError, KeyError):
                pass
