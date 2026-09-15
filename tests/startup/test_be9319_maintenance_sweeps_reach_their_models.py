# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from api.startup import background_tasks
from api.startup.background_tasks import purge_old_notifications_task
from api.startup.soft_delete_reaper import purge_expired_soft_deleted_entities
from giljo_mcp import tenant_guard
from giljo_mcp.models import AgentTemplate, APIKey, Task, VisionDocument
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.notifications import Notification
from giljo_mcp.tenant import TenantManager




def _registered() -> frozenset[type]:
    return tenant_guard._CE_TENANT_SCOPED_MODELS | frozenset(tenant_guard._REGISTERED_TENANT_SCOPED_MODELS)


def _tenant_isolation_errors(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.ERROR and "Tenant context required" in r.getMessage()
    ]




def test_every_model_these_sweeps_enumerate_is_registered():
    registered = _registered()
    for model in (Notification, CommThread, Task, VisionDocument, AgentTemplate, APIKey):
        assert model in registered, (
            f"{model.__name__} is NOT in the tenant-isolation registry. Both BE-9319 sites "
            "assume registration; an unregistered model needs the no-bypass path instead."
        )


def test_the_bypass_accepts_a_registered_model_and_rejects_an_unregistered_one():
    import inspect

    src = inspect.getsource(tenant_guard.tenant_isolation_bypass)
    assert "not tenant-scoped" in src, (
        "the bypass's rejection is expected to key on NOT-tenant-scoped models; if that changed, "
        "the BE-9319 reasoning needs re-checking"
    )




async def test_notification_retention_sweep_reaches_its_query(db_manager, monkeypatch, caplog):
    real_sleep = asyncio.sleep
    calls = {"n": 0}

    async def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(background_tasks.asyncio, "sleep", fake_sleep)
    state = SimpleNamespace(db_manager=db_manager, websocket_manager=None)

    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await purge_old_notifications_task(state)

    errors = _tenant_isolation_errors(caplog)
    assert not errors, (
        "the notification retention sweep must reach its cross-tenant enumeration; the guard "
        f"blocked it instead: {errors}"
    )




async def test_soft_delete_reaper_reaches_all_four_models(db_manager, caplog):
    with caplog.at_level(logging.ERROR):
        await purge_expired_soft_deleted_entities(db_manager, TenantManager())

    errors = _tenant_isolation_errors(caplog)
    assert not errors, (
        "the soft-delete reaper must reach every model it enumerates; the guard blocked it "
        f"instead, which also skips the three models after it: {errors}"
    )


async def test_the_reaper_leaves_isolation_exactly_as_it_found_it(db_manager, caplog):
    from sqlalchemy import select

    from giljo_mcp.tenant_guard import TenantIsolationError

    with caplog.at_level(logging.ERROR):
        await purge_expired_soft_deleted_entities(db_manager, TenantManager())
    assert not _tenant_isolation_errors(caplog), "precondition: the sweep itself must be clean"

    async with db_manager.get_session_async() as session:
        with pytest.raises(TenantIsolationError):
            await session.execute(select(CommThread.tenant_key).distinct())


def test_the_caller_supplied_bypass_opinion_is_gone_for_good():
    import ast
    import inspect

    from api.startup import soft_delete_reaper

    tree = ast.parse(inspect.getsource(soft_delete_reaper))
    offenders = [
        f"{node.name}({arg.arg})"
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for arg in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]
        if "bypass" in arg.arg
    ]
    assert not offenders, (
        f"a caller-supplied bypass flag is back in the reaper: {offenders}. Registry membership "
        "is a fact the guard already knows — let tenant_isolation_bypass reject an unregistered "
        "model by name; do not ask the caller to remember it."
    )


async def test_soft_delete_reaper_does_not_abandon_the_later_models(db_manager, caplog):
    with caplog.at_level(logging.ERROR):
        await purge_expired_soft_deleted_entities(db_manager, TenantManager())

    failures = [r.getMessage() for r in caplog.records if "Failed to reap expired soft-deleted rows" in r.getMessage()]
    assert not failures, (
        f"the reaper reported a failure, so the models enumerated after the failing one never ran: {failures}"
    )
