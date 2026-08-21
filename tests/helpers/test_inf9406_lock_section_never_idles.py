# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9406 -- the CREATE DATABASE lock is never held across work on another connection.

``DB_CREATE_LOCK_KEY`` is a PostgreSQL advisory lock, and advisory locks are
CLUSTER-scoped: every xdist worker and every concurrent clone on the server
queues on the one key, however disjoint their database names are. The cost of
that critical section is therefore paid by the whole box, not by the holder.

``ensure_test_database_exists`` used to hold it across two operations issued on
OTHER connections -- the read-only ``_missing_columns`` diff and
``drop_test_database()``, each of which builds its own engine -- so the holder
sat ``idle`` for as long as they took. Measured on this box: a holder idle 27s
on the existence check while two sessions waited 24s on ``pg_advisory_lock``,
which took the BE-9288 guard test's body to 33.1s against the 30s ``--timeout``
in pyproject.toml. ``--timeout-method=thread`` kills by ``os._exit(1)``, so it
landed as a dead xdist worker and a red suite rather than as a slow test.

Removing that idle hold was necessary and NOT sufficient, which is the second
invariant here. A holder that is BUSY the whole time still stalls every other
clone if the work is itself cluster-wide: ``DROP DATABASE`` forces a
cluster-wide immediate checkpoint and waits for it, so its duration is a
function of every OTHER worker's dirty buffers. Measured during a concurrent
two-tree ``-n 6`` pair -- with the idle hold already fixed -- one holder sat
ACTIVE for **34.30s** on a single ``DROP DATABASE``, a sibling clone's worker
blocked **28.54s** behind it, and BOTH died: the waiter on the queue, the holder
on its own statement inside its own 30s-timed body. Solo runs never reproduced
it because solo, nothing else has dirtied the cluster.

This is a SOURCE-STRUCTURE guard, not a behaviour test, and deliberately so: the
regression is invisible at runtime. Moving a call back inside the lock still
passes every functional test -- it only makes the box slower, and only under a
concurrency the unit suite never creates. So both invariants are enforced where
they can actually be seen:

1. **every await inside the critical section must await ``conn.execute(...)``**,
   on the connection that holds the lock (no idle hold); and
2. **no ``DROP DATABASE``, ``DROP SCHEMA`` or ``pg_terminate_backend`` inside
   it** -- the lock exists for the ``template1`` copy, so ``CREATE DATABASE`` is
   the only thing that belongs there. Rule 1 alone would pass a drop reissued on
   ``conn``, which is precisely the 34.30s failure above.

Both are paired with a check that the thing they protect still HAPPENS -- the
drift diff still runs, and the drift response still resets the schema -- because
the cheapest way to satisfy a "not inside the lock" rule is to delete the work
entirely, which would retire BE-9288's guarantee with every guard still green.

Sibling guard: ``test_tsk9381_one_create_database_lock.py`` (one key, one place).
"""

from __future__ import annotations

import ast
from pathlib import Path


_HELPER = Path(__file__).resolve().parent / "test_db_helper.py"
_FUNCTION = "ensure_test_database_exists"
_LOCK_CM = "create_database_lock_async"


def _function_node() -> ast.AsyncFunctionDef:
    tree = ast.parse(_HELPER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == _FUNCTION:
            return node
    raise AssertionError(f"{_FUNCTION} is gone from {_HELPER.name}. Re-point this guard rather than deleting it.")


def _locked_block(function: ast.AsyncFunctionDef) -> tuple[ast.AsyncWith, str]:
    """The ``async with create_database_lock_async(<conn>)`` block, and that conn's name.

    Takes the function node rather than re-reading the file: the inside/outside
    test below compares node identity, and two separate ``ast.parse`` calls
    produce two disjoint trees in which nothing is ever the same object.
    """
    for node in ast.walk(function):
        if not isinstance(node, ast.AsyncWith):
            continue
        for item in node.items:
            call = item.context_expr
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == _LOCK_CM:
                assert call.args and isinstance(call.args[0], ast.Name), (
                    f"{_LOCK_CM} must be handed a plain connection name so this guard can tell "
                    "which connection holds the lock."
                )
                return node, call.args[0].id
    raise AssertionError(
        f"{_FUNCTION} no longer takes {_LOCK_CM}. That is not a shorter critical section, it is "
        "no serialization at all -- concurrent template1 copies come back (TSK-9381)."
    )


def _is_execute_on(node: ast.expr, conn: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == conn
    )


def _render(node: ast.expr) -> str:
    try:
        return ast.unparse(node).split("\n")[0][:120]
    except Exception:  # pragma: no cover - ast.unparse is available on 3.9+
        return f"<{type(node).__name__}>"


def test_every_await_inside_the_lock_runs_on_the_lock_holding_connection():
    """Nothing in the critical section may do I/O on a different connection.

    An await on anything else -- another engine's connection, a helper that
    builds one -- leaves the holder idle while the entire cluster queues behind
    it. That is INF-9406's whole failure mode, and it reads as ordinary code.
    """
    block, conn = _locked_block(_function_node())

    offenders = [
        _render(node.value)
        for statement in block.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Await) and not _is_execute_on(node.value, conn)
    ]

    assert offenders == [], (
        f"These awaits sit inside the {_LOCK_CM} block without running on '{conn}': {offenders}. "
        f"DB_CREATE_LOCK_KEY is cluster-scoped, so anything awaited on another connection leaves "
        f"the holder idle while every other worker and clone on this server waits for it. Do the "
        f"work before taking the lock, or issue it on '{conn}'."
    )


def test_nothing_inside_the_lock_opens_another_connection():
    """An ``async with`` on another engine would smuggle I/O past the await check.

    ``async with engine.connect()`` produces no ``Await`` node, so pin it
    separately: the critical section opens no context managers of its own.
    """
    block, conn = _locked_block(_function_node())

    offenders = [
        _render(item.context_expr)
        for statement in block.body
        for node in ast.walk(statement)
        if isinstance(node, ast.AsyncWith)
        for item in node.items
    ]

    assert offenders == [], (
        f"These context managers are entered inside the {_LOCK_CM} block: {offenders}. Opening a "
        f"connection or engine there is the idle hold INF-9406 removed -- the lock is held while "
        f"the handshake happens somewhere else. Everything in the block runs on '{conn}'."
    )


def test_the_drift_diff_still_runs_and_runs_outside_the_lock():
    """The cheap way to satisfy the guards above would be to stop diffing at all.

    That would silently retire BE-9288's schema-drift detection, so pin both
    halves: ``_missing_columns`` is still called, and it is called outside the
    critical section.
    """
    function = _function_node()
    block, _conn = _locked_block(function)

    inside = {id(node) for node in ast.walk(block)}
    diff_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "_missing_columns"
    ]

    assert diff_calls, (
        f"{_FUNCTION} no longer calls _missing_columns. Deleting the schema-drift diff is not a "
        "valid way to shorten the lock window -- it retires BE-9288's guarantee."
    )
    assert all(id(node) not in inside for node in diff_calls), (
        "_missing_columns is back INSIDE the create-database lock. It is read-only and runs on its "
        "own engine, so holding the cluster-wide lock across it stalls every other worker and "
        "clone for nothing (INF-9406)."
    )


def _sql_literals(node: ast.AST) -> list[str]:
    """Every string constant under ``node``, whitespace-collapsed and upper-cased."""
    return [
        " ".join(n.value.split()).upper()
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


# Statements whose cost is paid by the whole cluster, not by the holder, and
# which therefore must never sit inside a cluster-scoped lock.
_BANNED_IN_LOCK = ("DROP DATABASE", "DROP SCHEMA", "PG_TERMINATE_BACKEND")


def test_no_cluster_wide_ddl_sits_inside_the_lock():
    """The critical section holds only ``CREATE DATABASE`` (INF-9406, second half).

    The idle-hold rule above is necessary and was NOT sufficient: a holder that
    is busy the whole time still stalls every other clone if what it is busy
    WITH is cluster-wide. ``DROP DATABASE`` forces a cluster-wide immediate
    checkpoint and waits for it, so its duration is a function of every other
    worker's dirty buffers -- measured at 0.47s on an idle cluster and **34.30s**
    during a concurrent two-tree ``-n 6`` pair, which killed both the holder and
    a sibling clone's worker blocked 28.54s behind it.

    So the ban is on the STATEMENTS, not on where they execute: putting the drop
    back on ``conn`` would satisfy every other check in this file and reinstate
    the exact failure. ``pg_terminate_backend`` is banned with them because it
    only ever appears as their prelude.
    """
    block, _conn = _locked_block(_function_node())

    offenders = sorted({banned for sql in _sql_literals(block) for banned in _BANNED_IN_LOCK if banned in sql})

    assert offenders == [], (
        f"These cluster-wide statements are inside the {_LOCK_CM} block: {offenders}. "
        f"DB_CREATE_LOCK_KEY is cluster-scoped and DROP DATABASE forces a cluster-wide checkpoint, "
        f"so holding the key across one makes this critical section as long as every OTHER "
        f"worker's write volume (measured: 34.30s, against a 30s per-test timeout). The lock exists "
        f"for the template1 copy -- CREATE DATABASE -- and nothing else belongs in it."
    )


def test_the_drift_response_still_happens_and_runs_outside_the_lock():
    """The cheap way to satisfy the ban above would be to stop responding to drift.

    That would leave the diff running and its answer unused -- BE-9288's
    guarantee retired while every guard in this file still passed. So pin both
    halves: the schema reset exists, and it is outside the critical section.
    """
    function = _function_node()
    block, _conn = _locked_block(function)

    inside = {id(node) for node in ast.walk(block)}
    # Scoped to ``text(...)`` calls, NOT to every string constant in the
    # function: this docstring and the module's own prose both say "DROP
    # SCHEMA", so a constant-wide search matches the DOCUMENTATION and passes
    # while the code does nothing. Caught by a mutation probe -- deleting the
    # reset left this test green until it was narrowed to executable SQL.
    #
    # The asymmetry is deliberate and worth keeping: a BAN (above) should
    # over-approximate, because a false positive only costs an argument. An
    # EXISTENCE requirement must under-approximate, because anything it matches
    # by accident is a guarantee it stops guarding.
    resets = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "text"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and "DROP SCHEMA" in node.args[0].value.upper()
    ]

    assert resets, (
        f"{_FUNCTION} no longer resets the schema on drift. Detecting drift and doing nothing about "
        "it retires BE-9288's guarantee just as completely as deleting the diff would -- and it is "
        "the cheapest way to make the rest of this file green."
    )
    assert all(id(node) not in inside for node in resets), (
        "The drift reset is INSIDE the create-database lock. It copies no template1 and forces no "
        "checkpoint, so it needs no cluster-wide lock -- and holding one across it is how INF-9406 "
        "killed two workers at once."
    )
