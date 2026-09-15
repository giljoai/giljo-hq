# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    return [
        " ".join(n.value.split()).upper()
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


_BANNED_IN_LOCK = ("DROP DATABASE", "DROP SCHEMA", "PG_TERMINATE_BACKEND")


def test_no_cluster_wide_ddl_sits_inside_the_lock():
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
    function = _function_node()
    block, _conn = _locked_block(function)

    inside = {id(node) for node in ast.walk(block)}
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
