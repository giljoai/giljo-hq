# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib
import inspect

import pytest

from giljo_mcp import database
from giljo_mcp.database import (
    TENANT_SCOPED_MODELS,
    register_tenant_scoped_models,
    tenant_isolation_bypass,
)
from giljo_mcp.models import Project


class _DummyTenantScoped:
    pass


class _FakeSession:

    def __init__(self) -> None:
        self.info: dict = {}


@pytest.fixture
def reset_registry():
    snapshot = set(database._REGISTERED_TENANT_SCOPED_MODELS)
    try:
        yield
    finally:
        database._REGISTERED_TENANT_SCOPED_MODELS.clear()
        database._REGISTERED_TENANT_SCOPED_MODELS.update(snapshot)
        register_tenant_scoped_models()


def test_unregistered_model_is_rejected(reset_registry) -> None:
    with pytest.raises(ValueError, match="not tenant-scoped"):
        with tenant_isolation_bypass(
            _FakeSession(),
            reason="BE-6031a: unregistered model must be rejected",
            models=(_DummyTenantScoped,),
        ):
            pass


def test_registered_model_is_accepted(reset_registry) -> None:
    register_tenant_scoped_models(_DummyTenantScoped)

    with tenant_isolation_bypass(
        _FakeSession(),
        reason="BE-6031a: registered model is accepted",
        models=(_DummyTenantScoped,),
    ):
        pass

    assert _DummyTenantScoped in database._all_tenant_scoped_models()


def test_ce_builtin_still_accepted(reset_registry) -> None:
    assert Project in TENANT_SCOPED_MODELS

    with tenant_isolation_bypass(
        _FakeSession(),
        reason="BE-6031a: CE built-in still accepted",
        models=(Project,),
    ):
        pass


def test_registration_is_idempotent(reset_registry) -> None:
    register_tenant_scoped_models(_DummyTenantScoped)
    size_after_first = len(database._REGISTERED_TENANT_SCOPED_MODELS)

    register_tenant_scoped_models(_DummyTenantScoped)
    size_after_second = len(database._REGISTERED_TENANT_SCOPED_MODELS)

    assert size_after_first == size_after_second
    with tenant_isolation_bypass(
        _FakeSession(),
        reason="BE-6031a: idempotent re-registration still works",
        models=(_DummyTenantScoped,),
    ):
        pass


def test_registration_is_additive_only(reset_registry) -> None:
    before = set(database._all_tenant_scoped_models())
    register_tenant_scoped_models(_DummyTenantScoped)
    after = set(database._all_tenant_scoped_models())

    assert before.issubset(after)
    assert after - before == {_DummyTenantScoped}


def test_public_union_name_reflects_registered_models(reset_registry) -> None:
    register_tenant_scoped_models(_DummyTenantScoped)
    assert _DummyTenantScoped in database.TENANT_SCOPED_MODELS
    assert Project in database.TENANT_SCOPED_MODELS


def test_scoped_tables_reflect_registered_models(reset_registry) -> None:
    tables = database._all_tenant_scoped_tables()
    assert Project.__table__ in tables
    assert tables[Project.__table__] is Project


def test_registration_invalidates_memoized_cache(reset_registry) -> None:
    assert Project not in database._REGISTERED_TENANT_SCOPED_MODELS

    models_before = database._all_tenant_scoped_models()
    tables_before = database._all_tenant_scoped_tables()
    assert _DummyTenantScoped not in models_before

    register_tenant_scoped_models(_DummyTenantScoped)

    models_after = database._all_tenant_scoped_models()
    tables_after = database._all_tenant_scoped_tables()
    assert _DummyTenantScoped in models_after
    assert _DummyTenantScoped not in set(tables_after.values())
    assert models_after is not models_before
    assert tables_after is not tables_before


def test_scoped_table_dict_read_is_cached_identity(reset_registry) -> None:
    first = database._all_tenant_scoped_tables()
    second = database._all_tenant_scoped_tables()
    assert first is second


def test_database_module_imports_no_saas() -> None:
    source = inspect.getsource(importlib.import_module("giljo_mcp.database"))
    assert "giljo_mcp.saas" not in source
    assert "from .saas" not in source
    assert "import saas" not in source
