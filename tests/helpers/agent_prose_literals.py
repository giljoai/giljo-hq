# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})


def _developer_only_literals(tree: ast.AST) -> set[int]:
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            skip.add(id(node.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS:
            for arg in ast.walk(node):
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) or isinstance(arg, ast.JoinedStr):
                    skip.add(id(arg))
    return skip


def _mapping_key_literals(tree: ast.AST) -> set[int]:
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    skip.add(id(key))
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                skip.add(id(node.slice))
    return skip


def _string_constants(path: Path, *, require_whitespace: bool) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _developer_only_literals(tree)
    if not require_whitespace:
        skip |= _mapping_key_literals(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        if require_whitespace and not any(ch.isspace() for ch in node.value):
            continue
        out.append((node.lineno, node.value))
    return out


def prose_literals(path: Path) -> list[tuple[int, str]]:
    return _string_constants(path, require_whitespace=True)


def all_string_literals(path: Path) -> list[tuple[int, str]]:
    return _string_constants(path, require_whitespace=False)


def interpolated_names(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _developer_only_literals(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or id(node) in skip:
            continue
        for part in node.values:
            if not isinstance(part, ast.FormattedValue):
                continue
            expr = part.value
            if isinstance(expr, ast.Name):
                name = expr.id
            elif isinstance(expr, ast.Attribute):
                name = expr.attr
            else:
                name = ast.unparse(expr)
            out.append((node.lineno, name))
    return out


def python_files(*relative_roots: str) -> list[Path]:
    files: list[Path] = []
    for rel in relative_roots:
        target = REPO_ROOT / rel
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
        elif target.suffix == ".py":
            files.append(target)
        else:
            raise AssertionError(f"scan root {rel!r} does not exist -- fix the list, do not silence it")
    return files
