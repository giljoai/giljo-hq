# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9319 — two maintenance sweeps died on a comment that was no longer true.

Both failed on the LAN CE box, every run, silently:

    background_tasks.py:552  select(Notification.tenant_key).distinct()
      -> TenantIsolationError: Tenant context required for ORM statement touching: Notification
    soft_delete_reaper.py:67 _tenants_with_expired(session, CommThread, needs_bypass=False)
      -> TenantIsolationError: Tenant context required for ORM statement touching: CommThread

Each site carried a comment asserting the model was "intentionally NOT in the
tenant-isolation guard registry", so its cross-tenant enumeration needed no
bypass. The reaper's comment cited Notification as corroboration; the
Notification comment rested on the same belief. One false premise, written down
twice, each citing the other.

Measured against the running registry (41 models): Notification, CommThread,
Task, VisionDocument, AgentTemplate and APIKey are ALL registered. The registry
records when it happened — CommThread in SEC-9272, Notification in SEC-9276 —
three files away from the code that denies it. The comments were true when
written and nobody swept the callers that depended on their absence.

The second claim inverts the same way. "Wrapping it in one would raise (the
bypass rejects non-registered models)" describes the bypass correctly — it does
raise for a NON-tenant-scoped model — but these models ARE tenant-scoped, so the
bypass accepts them and is exactly the right mechanism.

WHY IT SURVIVED: ``tests/services/test_tsk6132_softdelete_reaper.py`` covers the
per-service ``purge_expired_deleted_*`` methods thoroughly, and every one passes.
Nothing drove ``purge_expired_soft_deleted_entities`` — the orchestrator that
holds the defect. The layer with the bug had no test, which is the BE-5042 class
CLAUDE.md mandates a failing-layer regression for. These tests are at that layer.

THE BLAST IS WIDER THAN ONE MODEL: CommThread is enumerated FIRST, and the whole
body sits in one try. It raises, the block exits, and Task / VisionDocument /
AgentTemplate are never enumerated either. Four models' soft-deleted rows
accumulate forever, not one — and a CE self-hoster has no operator to clean them.

Both sweeps fail CLOSED, so this is a broken purge, never an isolation hole. The
two-sided half below pins that the fix keeps it that way.

Parallel-safe: no module-level mutable state, monkeypatched sleep, fresh tenant
keys per test.

Edition Scope: Both.
"""

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


# No module-level asyncio mark: the suite runs --asyncio-mode=auto, and marking a
# module that also holds sync guard tests warns on every one of them (BE-9303).


def _registered() -> frozenset[type]:
    """The guard's effective model set, read from the guard rather than a doc."""
    return tenant_guard._CE_TENANT_SCOPED_MODELS | frozenset(tenant_guard._REGISTERED_TENANT_SCOPED_MODELS)


def _tenant_isolation_errors(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.ERROR and "Tenant context required" in r.getMessage()
    ]


# ---------------------------------------------------------------------------
# The claim both comments rest on — settled against the running system.
# ---------------------------------------------------------------------------


def test_every_model_these_sweeps_enumerate_is_registered():
    """The comments' load-bearing premise, checked against the registry itself.

    If this ever goes red, a model left the registry and the sweeps' bypasses
    must be revisited — which is the opposite failure and equally worth knowing.
    """
    registered = _registered()
    for model in (Notification, CommThread, Task, VisionDocument, AgentTemplate, APIKey):
        assert model in registered, (
            f"{model.__name__} is NOT in the tenant-isolation registry. Both BE-9319 sites "
            "assume registration; an unregistered model needs the no-bypass path instead."
        )


def test_the_bypass_accepts_a_registered_model_and_rejects_an_unregistered_one():
    """Pins the mechanic the comments got backwards.

    The bypass raises for a model that is not tenant-scoped — the comments were
    right about that — but these models ARE tenant-scoped, so it accepts them.
    """
    import inspect

    src = inspect.getsource(tenant_guard.tenant_isolation_bypass)
    assert "not tenant-scoped" in src, (
        "the bypass's rejection is expected to key on NOT-tenant-scoped models; if that changed, "
        "the BE-9319 reasoning needs re-checking"
    )


# ---------------------------------------------------------------------------
# Failing layer 1 — the notification retention sweep.
# ---------------------------------------------------------------------------


async def test_notification_retention_sweep_reaches_its_query(db_manager, monkeypatch, caplog):
    """RED before fix: TenantIsolationError on Notification, every 6 hours, forever.

    Drives the REAL loop through exactly one iteration using the house
    ``fake_sleep`` idiom (BE-9053), so this is the background task failing, not a
    service-level substitute.
    """
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


# ---------------------------------------------------------------------------
# Failing layer 2 — the soft-delete reaper orchestrator.
# ---------------------------------------------------------------------------


async def test_soft_delete_reaper_reaches_all_four_models(db_manager, caplog):
    """RED before fix: TenantIsolationError on CommThread — the FIRST of four.

    The orchestrator wraps all four enumerations in one try, so the raise skips
    Task, VisionDocument and AgentTemplate as well. This asserts the sweep runs
    clean, which is the only outcome in which all four are actually enumerated.
    """
    with caplog.at_level(logging.ERROR):
        await purge_expired_soft_deleted_entities(db_manager, TenantManager())

    errors = _tenant_isolation_errors(caplog)
    assert not errors, (
        "the soft-delete reaper must reach every model it enumerates; the guard blocked it "
        f"instead, which also skips the three models after it: {errors}"
    )


async def test_the_reaper_leaves_isolation_exactly_as_it_found_it(db_manager, caplog):
    """THE LOAD-BEARING HALF. The fix adds a bypass; the bypass must not linger.

    A fix that restores the purge by weakening isolation is a far worse bug than
    the broken purge. So after a full reaper run, an unscoped statement touching
    the same model must STILL be refused — proving the bypass was confined to its
    ``with`` block and to the model it named, and that the per-tenant purges that
    follow it run tenant-scoped as before.
    """
    from sqlalchemy import select

    from giljo_mcp.tenant_guard import TenantIsolationError

    with caplog.at_level(logging.ERROR):
        await purge_expired_soft_deleted_entities(db_manager, TenantManager())
    assert not _tenant_isolation_errors(caplog), "precondition: the sweep itself must be clean"

    async with db_manager.get_session_async() as session:
        with pytest.raises(TenantIsolationError):
            await session.execute(select(CommThread.tenant_key).distinct())


def test_the_caller_supplied_bypass_opinion_is_gone_for_good():
    """The defect was a hand-typed boolean encoding a fact the registry owns.

    Correcting the one wrong call site would have left the next author the same
    trap. This fails if a ``needs_bypass``-style parameter is reintroduced, which
    is the shape of the bug rather than the instance of it.
    """
    import ast
    import inspect

    from api.startup import soft_delete_reaper

    # Parsed, not grepped: a substring search matches this file's own prose
    # explaining the removed flag, which is how a guard ends up asserting against
    # a comment instead of the code. Check real parameter names.
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
    """The ordering consequence, pinned separately from the raise itself.

    A future edit could 'fix' the first enumeration and leave the all-in-one-try
    structure, so a raise on any single model would still silently skip the rest.
    Asserting the run logs no failure at all is what keeps the other three
    covered.
    """
    with caplog.at_level(logging.ERROR):
        await purge_expired_soft_deleted_entities(db_manager, TenantManager())

    failures = [r.getMessage() for r in caplog.records if "Failed to reap expired soft-deleted rows" in r.getMessage()]
    assert not failures, (
        f"the reaper reported a failure, so the models enumerated after the failing one never ran: {failures}"
    )
